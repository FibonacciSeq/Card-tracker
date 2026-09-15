/*  Card-tracker :: 09 - procedure za porudzbine                             */

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE CardTracker;
GO

CREATE OR ALTER PROCEDURE sales.usp_CreateOrder
(
    @CustomerId INT,
    @Note       NVARCHAR(500) = NULL,
    @OrderId    INT           = NULL OUTPUT
)
AS
BEGIN
    SET NOCOUNT ON;

    IF NOT EXISTS (SELECT 1 FROM sales.Customer WHERE CustomerId = @CustomerId AND IsActive = 1)
    BEGIN
        THROW 50020, N'Kupac ne postoji ili nije aktivan.', 1;
    END

    INSERT INTO sales.CustomerOrder (CustomerId, Note)
    VALUES (@CustomerId, @Note);

    SET @OrderId = CAST(SCOPE_IDENTITY() AS INT);
    RETURN 0;
END
GO


CREATE OR ALTER PROCEDURE sales.usp_AddOrderLine
(
    @OrderId       INT,
    @CardId        INT,
    @Quantity      INT,
    @IsFoil        BIT           = 0,
    @ConditionCode NVARCHAR(4)   = NULL,   -- NULL = kupcu je svejedno
    @UnitPriceRsd  DECIMAL(12,2) = NULL,   -- NULL = uzmi iz cenovnika
    @OrderLineId   INT           = NULL OUTPUT
)
AS
BEGIN
    SET NOCOUNT ON;

    IF @Quantity <= 0
    BEGIN
        THROW 50021, N'Količina mora biti veća od nule.', 1;
    END

    IF NOT EXISTS (SELECT 1 FROM sales.CustomerOrder WHERE OrderId = @OrderId AND OrderStatus IN (N'OPEN', N'PARTIAL'))
    BEGIN
        THROW 50022, N'Porudžbina ne postoji ili je zatvorena.', 1;
    END

    /*  Bez zadate cene koristi se trenutni cenovnik, da se cena "zamrzne"
        u trenutku porudzbine i ne menja se kad Scryfall promeni cenu.       */
    IF @UnitPriceRsd IS NULL
    BEGIN
        SELECT @UnitPriceRsd = catalog.fn_RetailPriceRsd(
                                   CASE WHEN @IsFoil = 1 THEN PriceEurFoil ELSE PriceEur END,
                                   catalog.fn_CurrentEurToRsd())
        FROM catalog.Card
        WHERE CardId = @CardId;
    END

    INSERT INTO sales.OrderLine (OrderId, CardId, IsFoil, ConditionCode, QuantityOrdered, UnitPriceRsd)
    VALUES (@OrderId, @CardId, @IsFoil, @ConditionCode, @Quantity, @UnitPriceRsd);

    SET @OrderLineId = CAST(SCOPE_IDENTITY() AS INT);
    RETURN 0;
END
GO


/*  Rezervise slobodnu zalihu na otvorene stavke.

    Redosled je FIFO po datumu porudzbine: ko je prvi trazio, prvi dobija.
    Trosi se najlosije stanje koje jos zadovoljava zahtev kupca, da bi se
    bolji primerci sacuvali za kupce koji ih trazе.

    @OrderId = NULL znaci "prodji kroz sve otvorene porudzbine".             */
CREATE OR ALTER PROCEDURE sales.usp_AllocateStock
(
    @OrderId          INT = NULL,
    @AllocatedLines   INT = NULL OUTPUT,
    @AllocatedPieces  INT = NULL OUTPUT
)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    SET @AllocatedLines  = 0;
    SET @AllocatedPieces = 0;

    BEGIN TRANSACTION;

    DECLARE @OrderLineId INT, @CardId INT, @IsFoil BIT,
            @WantCondition NVARCHAR(4), @Outstanding INT;

    DECLARE line_cursor CURSOR LOCAL FAST_FORWARD FOR
        SELECT ol.OrderLineId, ol.CardId, ol.IsFoil, ol.ConditionCode,
               ol.QuantityOrdered - ol.QuantityAllocated
        FROM sales.OrderLine AS ol
        INNER JOIN sales.CustomerOrder AS o ON o.OrderId = ol.OrderId
        WHERE o.OrderStatus IN (N'OPEN', N'PARTIAL')
          AND ol.QuantityOrdered > ol.QuantityAllocated
          AND (@OrderId IS NULL OR ol.OrderId = @OrderId)
        ORDER BY o.PlacedUtc, ol.OrderLineId;

    OPEN line_cursor;
    FETCH NEXT FROM line_cursor INTO @OrderLineId, @CardId, @IsFoil, @WantCondition, @Outstanding;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        DECLARE @LineAllocated INT = 0;
        DECLARE @StockId INT, @Available INT;

        DECLARE stock_cursor CURSOR LOCAL FAST_FORWARD FOR
            SELECT s.StockId, s.Quantity - ISNULL(al.Allocated, 0)
            FROM inv.Stock AS s
            INNER JOIN inv.Condition AS cond
                ON cond.ConditionCode = s.ConditionCode
            OUTER APPLY
            (
                SELECT SUM(a.Quantity) AS Allocated
                FROM sales.Allocation AS a
                WHERE a.StockId = s.StockId AND a.ReleasedUtc IS NULL
            ) AS al
            WHERE s.CardId = @CardId
              AND s.IsFoil = @IsFoil
              AND s.Quantity - ISNULL(al.Allocated, 0) > 0
              /* Ako je kupac trazio stanje, ne smemo dati losije. */
              AND (@WantCondition IS NULL
                   OR cond.SortOrder <= (SELECT SortOrder FROM inv.Condition WHERE ConditionCode = @WantCondition))
            ORDER BY cond.SortOrder DESC, s.StockId;   -- prvo najlosije prihvatljivo

        OPEN stock_cursor;
        FETCH NEXT FROM stock_cursor INTO @StockId, @Available;

        WHILE @@FETCH_STATUS = 0 AND @LineAllocated < @Outstanding
        BEGIN
            DECLARE @Take INT =
                CASE WHEN @Available < (@Outstanding - @LineAllocated)
                     THEN @Available ELSE (@Outstanding - @LineAllocated) END;

            IF @Take > 0
            BEGIN
                INSERT INTO sales.Allocation (OrderLineId, StockId, Quantity)
                VALUES (@OrderLineId, @StockId, @Take);

                SET @LineAllocated = @LineAllocated + @Take;
            END

            FETCH NEXT FROM stock_cursor INTO @StockId, @Available;
        END

        CLOSE stock_cursor;
        DEALLOCATE stock_cursor;

        IF @LineAllocated > 0
        BEGIN
            UPDATE sales.OrderLine
            SET QuantityAllocated = QuantityAllocated + @LineAllocated
            WHERE OrderLineId = @OrderLineId;

            SET @AllocatedLines  = @AllocatedLines + 1;
            SET @AllocatedPieces = @AllocatedPieces + @LineAllocated;
        END

        FETCH NEXT FROM line_cursor INTO @OrderLineId, @CardId, @IsFoil, @WantCondition, @Outstanding;
    END

    CLOSE line_cursor;
    DEALLOCATE line_cursor;

    /*  Status porudzbine prati stavke. */
    UPDATE o
    SET OrderStatus = CASE
                          WHEN x.Outstanding = 0 THEN N'PARTIAL'   -- sve rezervisano, jos nije isporuceno
                          WHEN x.AnyAllocated = 1 THEN N'PARTIAL'
                          ELSE N'OPEN'
                      END
    FROM sales.CustomerOrder AS o
    CROSS APPLY
    (
        SELECT SUM(ol.QuantityOrdered - ol.QuantityAllocated) AS Outstanding,
               MAX(CASE WHEN ol.QuantityAllocated > 0 THEN 1 ELSE 0 END) AS AnyAllocated
        FROM sales.OrderLine AS ol
        WHERE ol.OrderId = o.OrderId
    ) AS x
    WHERE o.OrderStatus IN (N'OPEN', N'PARTIAL')
      AND (@OrderId IS NULL OR o.OrderId = @OrderId);

    COMMIT TRANSACTION;
    RETURN 0;
END
GO


/*  Isporuka: skida rezervisanu robu sa lagera i zatvara stavku.             */
CREATE OR ALTER PROCEDURE sales.usp_DeliverOrderLine
(
    @OrderLineId INT,
    @Quantity    INT = NULL   -- NULL = isporuci sve rezervisano
)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    BEGIN TRANSACTION;

    DECLARE @Allocated INT, @Delivered INT;

    SELECT @Allocated = QuantityAllocated, @Delivered = QuantityDelivered
    FROM sales.OrderLine WITH (UPDLOCK, HOLDLOCK)
    WHERE OrderLineId = @OrderLineId;

    IF @Allocated IS NULL
    BEGIN
        ROLLBACK TRANSACTION;
        THROW 50023, N'Stavka porudžbine ne postoji.', 1;
    END

    SET @Quantity = ISNULL(@Quantity, @Allocated - @Delivered);

    IF @Quantity <= 0 OR @Quantity > (@Allocated - @Delivered)
    BEGIN
        ROLLBACK TRANSACTION;
        THROW 50024, N'Nema toliko rezervisane robe za isporuku.', 1;
    END

    DECLARE @Remaining INT = @Quantity;
    DECLARE @AllocationId BIGINT, @StockId INT, @AllocQty INT, @CardId INT,
            @IsFoil BIT, @ConditionCode NVARCHAR(4), @LanguageCode NVARCHAR(5), @Location NVARCHAR(100);

    DECLARE alloc_cursor CURSOR LOCAL FAST_FORWARD FOR
        SELECT a.AllocationId, a.StockId, a.Quantity,
               s.CardId, s.IsFoil, s.ConditionCode, s.LanguageCode, s.Location
        FROM sales.Allocation AS a
        INNER JOIN inv.Stock AS s ON s.StockId = a.StockId
        WHERE a.OrderLineId = @OrderLineId AND a.ReleasedUtc IS NULL
        ORDER BY a.AllocationId;

    OPEN alloc_cursor;
    FETCH NEXT FROM alloc_cursor INTO @AllocationId, @StockId, @AllocQty,
                                      @CardId, @IsFoil, @ConditionCode, @LanguageCode, @Location;

    WHILE @@FETCH_STATUS = 0 AND @Remaining > 0
    BEGIN
        DECLARE @Ship INT = CASE WHEN @AllocQty < @Remaining THEN @AllocQty ELSE @Remaining END;

        /*  Rezervacija se prvo oslobadja, pa se roba skida - inace bi
            usp_AdjustStock odbio izmenu jer je kolicina jos "obecana".      */
        IF @Ship = @AllocQty
            UPDATE sales.Allocation SET ReleasedUtc = SYSUTCDATETIME() WHERE AllocationId = @AllocationId;
        ELSE
            UPDATE sales.Allocation SET Quantity = Quantity - @Ship WHERE AllocationId = @AllocationId;

        DECLARE @Delta INT = -@Ship;

        EXEC inv.usp_AdjustStock
            @CardId        = @CardId,
            @QuantityDelta = @Delta,
            @MovementType  = N'SALE',
            @IsFoil        = @IsFoil,
            @ConditionCode = @ConditionCode,
            @LanguageCode  = @LanguageCode,
            @Location      = @Location,
            @ReferenceType = N'ORDER_LINE',
            @ReferenceId   = @OrderLineId,
            @Note          = N'Isporuka';

        SET @Remaining = @Remaining - @Ship;

        FETCH NEXT FROM alloc_cursor INTO @AllocationId, @StockId, @AllocQty,
                                          @CardId, @IsFoil, @ConditionCode, @LanguageCode, @Location;
    END

    CLOSE alloc_cursor;
    DEALLOCATE alloc_cursor;

    UPDATE sales.OrderLine
    SET QuantityDelivered = QuantityDelivered + @Quantity
    WHERE OrderLineId = @OrderLineId;

    UPDATE o
    SET OrderStatus = N'FULFILLED', ClosedUtc = SYSUTCDATETIME()
    FROM sales.CustomerOrder AS o
    WHERE o.OrderId = (SELECT OrderId FROM sales.OrderLine WHERE OrderLineId = @OrderLineId)
      AND NOT EXISTS
      (
          SELECT 1 FROM sales.OrderLine AS ol
          WHERE ol.OrderId = o.OrderId AND ol.QuantityDelivered < ol.QuantityOrdered
      );

    COMMIT TRANSACTION;
    RETURN 0;
END
GO
