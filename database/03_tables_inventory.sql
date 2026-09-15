/*  Card-tracker :: 03 - zalihe                                              */

/*  Filtrirani indeksi i indeksirani pogledi zahtevaju ove opcije.
    SSMS ih podrazumevano ukljucuje, sqlcmd ne - zato eksplicitno.  */
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE CardTracker;
GO

/*  Stanje kartice. Ovo je deo identiteta artikla: ista karta u NM i u MP
    stanju su dva razlicita artikla sa razlicitom cenom.                     */
IF OBJECT_ID(N'inv.Condition', N'U') IS NULL
BEGIN
    CREATE TABLE inv.Condition
    (
        ConditionCode NVARCHAR(4)   NOT NULL,
        Name          NVARCHAR(50)  NOT NULL,
        SortOrder     TINYINT       NOT NULL,
        PriceFactor   DECIMAL(5,3)  NOT NULL,   -- mnozilac maloprodajne cene

        CONSTRAINT PK_Condition PRIMARY KEY CLUSTERED (ConditionCode),
        CONSTRAINT CK_Condition_PriceFactor CHECK (PriceFactor > 0 AND PriceFactor <= 1)
    );

    INSERT INTO inv.Condition (ConditionCode, Name, SortOrder, PriceFactor) VALUES
        (N'NM',  N'Near Mint',        1, 1.000),
        (N'LP',  N'Lightly Played',   2, 0.850),
        (N'MP',  N'Moderately Played',3, 0.700),
        (N'HP',  N'Heavily Played',   4, 0.500),
        (N'DMG', N'Damaged',          5, 0.300);

    PRINT 'Kreirana tabela inv.Condition';
END
GO

/*  Jedan red = jedan artikal na stanju.
    Kolicina se NIKADA ne menja direktno - vidi inv.usp_AdjustStock.          */
IF OBJECT_ID(N'inv.Stock', N'U') IS NULL
BEGIN
    CREATE TABLE inv.Stock
    (
        StockId        INT           IDENTITY(1,1) NOT NULL,
        CardId         INT           NOT NULL,
        IsFoil         BIT           NOT NULL CONSTRAINT DF_Stock_IsFoil DEFAULT (0),
        ConditionCode  NVARCHAR(4)   NOT NULL CONSTRAINT DF_Stock_Condition DEFAULT (N'NM'),
        LanguageCode   NVARCHAR(5)   NOT NULL CONSTRAINT DF_Stock_Language DEFAULT (N'en'),

        Quantity       INT           NOT NULL CONSTRAINT DF_Stock_Quantity DEFAULT (0),
        Location       NVARCHAR(100) NOT NULL CONSTRAINT DF_Stock_Location DEFAULT (N'MAIN'),
        UnitCostRsd    DECIMAL(12,2) NULL,       -- nabavna cena, za maržu

        CreatedUtc     DATETIME2(0)  NOT NULL CONSTRAINT DF_Stock_CreatedUtc DEFAULT (SYSUTCDATETIME()),
        ModifiedUtc    DATETIME2(0)  NOT NULL CONSTRAINT DF_Stock_ModifiedUtc DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_Stock PRIMARY KEY CLUSTERED (StockId),
        CONSTRAINT FK_Stock_Card FOREIGN KEY (CardId) REFERENCES catalog.Card (CardId),
        CONSTRAINT FK_Stock_Condition FOREIGN KEY (ConditionCode) REFERENCES inv.Condition (ConditionCode),
        CONSTRAINT CK_Stock_Quantity CHECK (Quantity >= 0),
        CONSTRAINT CK_Stock_UnitCost CHECK (UnitCostRsd IS NULL OR UnitCostRsd >= 0),
        /* Jedan artikal po lokaciji - sprecava duple redove za istu stvar. */
        CONSTRAINT UQ_Stock_Sku UNIQUE (CardId, IsFoil, ConditionCode, LanguageCode, Location)
    );

    CREATE INDEX IX_Stock_CardId ON inv.Stock (CardId) INCLUDE (Quantity, IsFoil, ConditionCode);

    PRINT 'Kreirana tabela inv.Stock';
END
GO

/*  Knjiga promena. Svaka izmena kolicine ostavlja trag, pa uvek moze da se
    odgovori "odakle ovih 12 komada" i da se stanje rekonstruise.             */
IF OBJECT_ID(N'inv.StockMovement', N'U') IS NULL
BEGIN
    CREATE TABLE inv.StockMovement
    (
        MovementId     BIGINT        IDENTITY(1,1) NOT NULL,
        StockId        INT           NOT NULL,
        MovementType   NVARCHAR(20)  NOT NULL,
        QuantityDelta  INT           NOT NULL,
        QuantityAfter  INT           NOT NULL,
        ReferenceType  NVARCHAR(30)  NULL,       -- npr. 'ORDER_LINE', 'IMPORT'
        ReferenceId    BIGINT        NULL,
        Note           NVARCHAR(400) NULL,
        OccurredUtc    DATETIME2(0)  NOT NULL CONSTRAINT DF_StockMovement_OccurredUtc DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_StockMovement PRIMARY KEY CLUSTERED (MovementId),
        CONSTRAINT FK_StockMovement_Stock FOREIGN KEY (StockId) REFERENCES inv.Stock (StockId),
        CONSTRAINT CK_StockMovement_Type CHECK (MovementType IN
            (N'PURCHASE', N'SALE', N'ADJUSTMENT', N'IMPORT', N'RETURN', N'WRITEOFF')),
        CONSTRAINT CK_StockMovement_Delta CHECK (QuantityDelta <> 0)
    );

    CREATE INDEX IX_StockMovement_Stock ON inv.StockMovement (StockId, OccurredUtc DESC);

    PRINT 'Kreirana tabela inv.StockMovement';
END
GO
