/*  Card-tracker :: 08 - procedure za zalihe                                 */

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE CardTracker;
GO

/*  JEDINI podrzan nacin da se promeni kolicina na stanju.

    Direktan UPDATE inv.Stock preskace knjigu promena, pa se posle ne zna
    odakle je stanje doslo. Ova procedura radi oboje u jednoj transakciji.

    Vraca StockId artikla.                                                   */
CREATE OR ALTER PROCEDURE inv.usp_AdjustStock
(
    @CardId        INT,
    @QuantityDelta INT,
    @MovementType  NVARCHAR(20)  = N'ADJUSTMENT',
    @IsFoil        BIT           = 0,
    @ConditionCode NVARCHAR(4)   = N'NM',
    @LanguageCode  NVARCHAR(5)   = N'en',
    @Location      NVARCHAR(100) = N'MAIN',
    @UnitCostRsd   DECIMAL(12,2) = NULL,
    @ReferenceType NVARCHAR(30)  = NULL,
    @ReferenceId   BIGINT        = NULL,
    @Note          NVARCHAR(400) = NULL,
    @StockId       INT           = NULL OUTPUT
)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;   -- svaka greska rollback-uje celu transakciju

    IF @QuantityDelta = 0
    BEGIN
        THROW 50010, N'QuantityDelta ne sme biti 0.', 1;
    END

    IF NOT EXISTS (SELECT 1 FROM catalog.Card WHERE CardId = @CardId)
    BEGIN
        THROW 50011, N'Kartica sa datim CardId ne postoji u katalogu.', 1;
    END

    BEGIN TRANSACTION;

    /*  UPDLOCK + HOLDLOCK: dva paralelna poziva za isti artikal moraju da se
        serijalizuju, inace se izgubi jedna izmena.                          */
    SELECT @StockId = StockId
    FROM inv.Stock WITH (UPDLOCK, HOLDLOCK)
    WHERE CardId        = @CardId
      AND IsFoil        = @IsFoil
      AND ConditionCode = @ConditionCode
      AND LanguageCode  = @LanguageCode
      AND Location      = @Location;

    IF @StockId IS NULL
    BEGIN
        IF @QuantityDelta < 0
        BEGIN
            ROLLBACK TRANSACTION;
            THROW 50012, N'Ne može se skinuti sa zalihe koja ne postoji.', 1;
        END

        INSERT INTO inv.Stock (CardId, IsFoil, ConditionCode, LanguageCode, Location, Quantity, UnitCostRsd)
        VALUES (@CardId, @IsFoil, @ConditionCode, @LanguageCode, @Location, 0, @UnitCostRsd);

        SET @StockId = CAST(SCOPE_IDENTITY() AS INT);
    END

    DECLARE @QuantityAfter INT;

    SELECT @QuantityAfter = Quantity + @QuantityDelta
    FROM inv.Stock
    WHERE StockId = @StockId;

    IF @QuantityAfter < 0
    BEGIN
        ROLLBACK TRANSACTION;
        THROW 50013, N'Zaliha ne može da ode u minus.', 1;
    END

    /*  Rezervisani komadi ne smeju da se odnesu ispod obecanog. */
    DECLARE @Allocated INT =
    (
        SELECT ISNULL(SUM(Quantity), 0)
        FROM sales.Allocation
        WHERE StockId = @StockId AND ReleasedUtc IS NULL
    );

    IF @QuantityAfter < @Allocated
    BEGIN
        ROLLBACK TRANSACTION;
        THROW 50014, N'Zaliha bi pala ispod količine rezervisane za kupce.', 1;
    END

    UPDATE inv.Stock
    SET Quantity    = @QuantityAfter,
        UnitCostRsd = COALESCE(@UnitCostRsd, UnitCostRsd),
        ModifiedUtc = SYSUTCDATETIME()
    WHERE StockId = @StockId;

    INSERT INTO inv.StockMovement
        (StockId, MovementType, QuantityDelta, QuantityAfter, ReferenceType, ReferenceId, Note)
    VALUES
        (@StockId, @MovementType, @QuantityDelta, @QuantityAfter, @ReferenceType, @ReferenceId, @Note);

    COMMIT TRANSACTION;

    RETURN 0;
END
GO
