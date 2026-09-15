/*  Card-tracker :: 04 - kupci i porudzbine ("stvari koje trebaju")          */

/*  Filtrirani indeksi i indeksirani pogledi zahtevaju ove opcije.
    SSMS ih podrazumevano ukljucuje, sqlcmd ne - zato eksplicitno.  */
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE CardTracker;
GO

IF OBJECT_ID(N'sales.Customer', N'U') IS NULL
BEGIN
    CREATE TABLE sales.Customer
    (
        CustomerId  INT           IDENTITY(1,1) NOT NULL,
        FullName    NVARCHAR(200) NOT NULL,
        Email       NVARCHAR(256) NULL,
        Phone       NVARCHAR(50)  NULL,
        Note        NVARCHAR(500) NULL,
        IsActive    BIT           NOT NULL CONSTRAINT DF_Customer_IsActive DEFAULT (1),
        CreatedUtc  DATETIME2(0)  NOT NULL CONSTRAINT DF_Customer_CreatedUtc DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_Customer PRIMARY KEY CLUSTERED (CustomerId)
    );

    /* Filtriran UNIQUE: e-mail je opcion, ali ako postoji mora biti jedinstven. */
    CREATE UNIQUE INDEX UQ_Customer_Email ON sales.Customer (Email) WHERE Email IS NOT NULL;

    PRINT 'Kreirana tabela sales.Customer';
END
GO

IF OBJECT_ID(N'sales.CustomerOrder', N'U') IS NULL
BEGIN
    CREATE TABLE sales.CustomerOrder
    (
        OrderId     INT           IDENTITY(1,1) NOT NULL,
        CustomerId  INT           NOT NULL,
        OrderStatus NVARCHAR(20)  NOT NULL CONSTRAINT DF_CustomerOrder_Status DEFAULT (N'OPEN'),
        PlacedUtc   DATETIME2(0)  NOT NULL CONSTRAINT DF_CustomerOrder_PlacedUtc DEFAULT (SYSUTCDATETIME()),
        ClosedUtc   DATETIME2(0)  NULL,
        Note        NVARCHAR(500) NULL,

        CONSTRAINT PK_CustomerOrder PRIMARY KEY CLUSTERED (OrderId),
        CONSTRAINT FK_CustomerOrder_Customer FOREIGN KEY (CustomerId) REFERENCES sales.Customer (CustomerId),
        CONSTRAINT CK_CustomerOrder_Status CHECK (OrderStatus IN
            (N'OPEN', N'PARTIAL', N'FULFILLED', N'CANCELLED'))
    );

    CREATE INDEX IX_CustomerOrder_Status ON sales.CustomerOrder (OrderStatus, PlacedUtc);

    PRINT 'Kreirana tabela sales.CustomerOrder';
END
GO

IF OBJECT_ID(N'sales.OrderLine', N'U') IS NULL
BEGIN
    CREATE TABLE sales.OrderLine
    (
        OrderLineId       INT           IDENTITY(1,1) NOT NULL,
        OrderId           INT           NOT NULL,
        CardId            INT           NOT NULL,
        IsFoil            BIT           NOT NULL CONSTRAINT DF_OrderLine_IsFoil DEFAULT (0),
        /* NULL = kupcu je svejedno stanje kartice. */
        ConditionCode     NVARCHAR(4)   NULL,

        QuantityOrdered   INT           NOT NULL,
        QuantityAllocated INT           NOT NULL CONSTRAINT DF_OrderLine_Allocated DEFAULT (0),
        QuantityDelivered INT           NOT NULL CONSTRAINT DF_OrderLine_Delivered DEFAULT (0),
        UnitPriceRsd      DECIMAL(12,2) NULL,     -- NULL = koristi cenovnik

        CreatedUtc        DATETIME2(0)  NOT NULL CONSTRAINT DF_OrderLine_CreatedUtc DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_OrderLine PRIMARY KEY CLUSTERED (OrderLineId),
        CONSTRAINT FK_OrderLine_Order FOREIGN KEY (OrderId)
            REFERENCES sales.CustomerOrder (OrderId) ON DELETE CASCADE,
        CONSTRAINT FK_OrderLine_Card FOREIGN KEY (CardId) REFERENCES catalog.Card (CardId),
        CONSTRAINT FK_OrderLine_Condition FOREIGN KEY (ConditionCode) REFERENCES inv.Condition (ConditionCode),
        CONSTRAINT CK_OrderLine_Ordered CHECK (QuantityOrdered > 0),
        /* Ne moze da se rezervise vise nego sto je naruceno, ni isporuci vise nego rezervisano. */
        CONSTRAINT CK_OrderLine_Allocated CHECK (QuantityAllocated BETWEEN 0 AND QuantityOrdered),
        CONSTRAINT CK_OrderLine_Delivered CHECK (QuantityDelivered BETWEEN 0 AND QuantityAllocated)
    );

    CREATE INDEX IX_OrderLine_Card ON sales.OrderLine (CardId, IsFoil)
        INCLUDE (QuantityOrdered, QuantityAllocated);

    PRINT 'Kreirana tabela sales.OrderLine';
END
GO

/*  Veza izmedju konkretne zalihe i stavke porudzbine. Bez ovoga se ne zna
    CIJI je rezervisani komad, pa dva kupca mogu da dobiju istu kartu.        */
IF OBJECT_ID(N'sales.Allocation', N'U') IS NULL
BEGIN
    CREATE TABLE sales.Allocation
    (
        AllocationId  BIGINT       IDENTITY(1,1) NOT NULL,
        OrderLineId   INT          NOT NULL,
        StockId       INT          NOT NULL,
        Quantity      INT          NOT NULL,
        AllocatedUtc  DATETIME2(0) NOT NULL CONSTRAINT DF_Allocation_AllocatedUtc DEFAULT (SYSUTCDATETIME()),
        ReleasedUtc   DATETIME2(0) NULL,

        CONSTRAINT PK_Allocation PRIMARY KEY CLUSTERED (AllocationId),
        CONSTRAINT FK_Allocation_OrderLine FOREIGN KEY (OrderLineId)
            REFERENCES sales.OrderLine (OrderLineId) ON DELETE CASCADE,
        CONSTRAINT FK_Allocation_Stock FOREIGN KEY (StockId) REFERENCES inv.Stock (StockId),
        CONSTRAINT CK_Allocation_Quantity CHECK (Quantity > 0)
    );

    CREATE INDEX IX_Allocation_Stock ON sales.Allocation (StockId) WHERE ReleasedUtc IS NULL;
    CREATE INDEX IX_Allocation_OrderLine ON sales.Allocation (OrderLineId);

    PRINT 'Kreirana tabela sales.Allocation';
END
GO
