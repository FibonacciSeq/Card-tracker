/*  Card-tracker :: 05 - pravila nabavke, staging i istorija ucitavanja      */

/*  Filtrirani indeksi i indeksirani pogledi zahtevaju ove opcije.
    SSMS ih podrazumevano ukljucuje, sqlcmd ne - zato eksplicitno.  */
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE CardTracker;
GO

/*  Kada zaliha padne ispod MinQuantity, dopunjava se do TargetQuantity.     */
IF OBJECT_ID(N'purchasing.ReorderRule', N'U') IS NULL
BEGIN
    CREATE TABLE purchasing.ReorderRule
    (
        ReorderRuleId  INT          IDENTITY(1,1) NOT NULL,
        CardId         INT          NOT NULL,
        IsFoil         BIT          NOT NULL CONSTRAINT DF_ReorderRule_IsFoil DEFAULT (0),
        MinQuantity    INT          NOT NULL,
        TargetQuantity INT          NOT NULL,
        IsActive       BIT          NOT NULL CONSTRAINT DF_ReorderRule_IsActive DEFAULT (1),
        Note           NVARCHAR(300) NULL,

        CONSTRAINT PK_ReorderRule PRIMARY KEY CLUSTERED (ReorderRuleId),
        CONSTRAINT FK_ReorderRule_Card FOREIGN KEY (CardId) REFERENCES catalog.Card (CardId),
        CONSTRAINT UQ_ReorderRule_Card UNIQUE (CardId, IsFoil),
        CONSTRAINT CK_ReorderRule_Min CHECK (MinQuantity >= 0),
        /* Dopuna mora da bude iznad praga, inace bi pravilo stalno okidalo. */
        CONSTRAINT CK_ReorderRule_Target CHECK (TargetQuantity > MinQuantity)
    );
    PRINT 'Kreirana tabela purchasing.ReorderRule';
END
GO

/* ------------------------------------------------------------------ ETL -- */

/*  Svako pokretanje posla ostavlja red ovde, pa u SSMS-u moze da se vidi
    sta je kada uslo i sta je odbijeno.                                      */
IF OBJECT_ID(N'etl.LoadRun', N'U') IS NULL
BEGIN
    CREATE TABLE etl.LoadRun
    (
        LoadRunId    BIGINT        IDENTITY(1,1) NOT NULL,
        JobName      NVARCHAR(100) NOT NULL,
        SourceName   NVARCHAR(400) NULL,
        StartedUtc   DATETIME2(0)  NOT NULL CONSTRAINT DF_LoadRun_StartedUtc DEFAULT (SYSUTCDATETIME()),
        FinishedUtc  DATETIME2(0)  NULL,
        LoadStatus   NVARCHAR(20)  NOT NULL CONSTRAINT DF_LoadRun_Status DEFAULT (N'RUNNING'),
        RowsRead     INT           NOT NULL CONSTRAINT DF_LoadRun_RowsRead DEFAULT (0),
        RowsInserted INT           NOT NULL CONSTRAINT DF_LoadRun_RowsInserted DEFAULT (0),
        RowsUpdated  INT           NOT NULL CONSTRAINT DF_LoadRun_RowsUpdated DEFAULT (0),
        RowsRejected INT           NOT NULL CONSTRAINT DF_LoadRun_RowsRejected DEFAULT (0),
        Message      NVARCHAR(2000) NULL,

        CONSTRAINT PK_LoadRun PRIMARY KEY CLUSTERED (LoadRunId),
        CONSTRAINT CK_LoadRun_Status CHECK (LoadStatus IN (N'RUNNING', N'SUCCESS', N'FAILED', N'PARTIAL'))
    );

    CREATE INDEX IX_LoadRun_Job ON etl.LoadRun (JobName, StartedUtc DESC);

    PRINT 'Kreirana tabela etl.LoadRun';
END
GO

/*  Odbijeni redovi. Ne ruse ucitavanje - zavrse ovde da bi se pregledali.   */
IF OBJECT_ID(N'etl.LoadError', N'U') IS NULL
BEGIN
    CREATE TABLE etl.LoadError
    (
        LoadErrorId  BIGINT         IDENTITY(1,1) NOT NULL,
        LoadRunId    BIGINT         NOT NULL,
        SourceRowNo  INT            NULL,
        ErrorMessage NVARCHAR(1000) NOT NULL,
        RawData      NVARCHAR(MAX)  NULL,
        CreatedUtc   DATETIME2(0)   NOT NULL CONSTRAINT DF_LoadError_CreatedUtc DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_LoadError PRIMARY KEY CLUSTERED (LoadErrorId),
        CONSTRAINT FK_LoadError_LoadRun FOREIGN KEY (LoadRunId)
            REFERENCES etl.LoadRun (LoadRunId) ON DELETE CASCADE
    );

    CREATE INDEX IX_LoadError_Run ON etl.LoadError (LoadRunId);

    PRINT 'Kreirana tabela etl.LoadError';
END
GO

/* -------------------------------------------------------------- staging -- */

/*  Sirovi Scryfall redovi. Sve je NVARCHAR jer ulazni podaci nisu provereni;
    konverzija i validacija se rade pri merge-u.                             */
IF OBJECT_ID(N'staging.ScryfallCard', N'U') IS NULL
BEGIN
    CREATE TABLE staging.ScryfallCard
    (
        StagingId       BIGINT        IDENTITY(1,1) NOT NULL,
        LoadRunId       BIGINT        NULL,
        ScryfallId      NVARCHAR(100) NULL,
        Name            NVARCHAR(250) NULL,
        SetCode         NVARCHAR(16)  NULL,
        SetName         NVARCHAR(250) NULL,
        CollectorNumber NVARCHAR(32)  NULL,
        TypeLine        NVARCHAR(400) NULL,
        Rarity          NVARCHAR(32)  NULL,
        Cmc             NVARCHAR(32)  NULL,
        Colors          NVARCHAR(32)  NULL,
        Layout          NVARCHAR(50)  NULL,
        ImageUrl        NVARCHAR(500) NULL,
        PriceUsd        NVARCHAR(32)  NULL,
        PriceUsdFoil    NVARCHAR(32)  NULL,
        PriceEur        NVARCHAR(32)  NULL,
        PriceEurFoil    NVARCHAR(32)  NULL,

        CONSTRAINT PK_StagingScryfallCard PRIMARY KEY CLUSTERED (StagingId)
    );
    PRINT 'Kreirana tabela staging.ScryfallCard';
END
GO

/*  Sirovi redovi iz Excel/CSV fajla sa zalihama.                            */
IF OBJECT_ID(N'staging.StockImport', N'U') IS NULL
BEGIN
    CREATE TABLE staging.StockImport
    (
        StagingId       BIGINT        IDENTITY(1,1) NOT NULL,
        LoadRunId       BIGINT        NULL,
        SourceRowNo     INT           NULL,
        CardName        NVARCHAR(250) NULL,
        SetCode         NVARCHAR(16)  NULL,
        CollectorNumber NVARCHAR(32)  NULL,
        Quantity        NVARCHAR(32)  NULL,
        IsFoil          NVARCHAR(16)  NULL,
        ConditionCode   NVARCHAR(16)  NULL,
        LanguageCode    NVARCHAR(16)  NULL,
        Location        NVARCHAR(100) NULL,
        UnitCostRsd     NVARCHAR(32)  NULL,

        CONSTRAINT PK_StagingStockImport PRIMARY KEY CLUSTERED (StagingId)
    );
    PRINT 'Kreirana tabela staging.StockImport';
END
GO
