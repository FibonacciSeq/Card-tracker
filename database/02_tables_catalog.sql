/*  Card-tracker :: 02 - katalog karata (referentni podaci sa Scryfall-a)     */

/*  Filtrirani indeksi i indeksirani pogledi zahtevaju ove opcije.
    SSMS ih podrazumevano ukljucuje, sqlcmd ne - zato eksplicitno.  */
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE CardTracker;
GO

IF OBJECT_ID(N'catalog.Card', N'U') IS NULL
BEGIN
    CREATE TABLE catalog.Card
    (
        CardId            INT              IDENTITY(1,1) NOT NULL,
        ScryfallId        UNIQUEIDENTIFIER NOT NULL,
        Name              NVARCHAR(250)    NOT NULL,
        SetCode           NVARCHAR(16)     NOT NULL,
        SetName           NVARCHAR(250)    NOT NULL,
        CollectorNumber   NVARCHAR(32)     NOT NULL,
        TypeLine          NVARCHAR(400)    NULL,
        Rarity            NVARCHAR(32)     NULL,
        Cmc               DECIMAL(6,2)     NOT NULL CONSTRAINT DF_Card_Cmc DEFAULT (0),
        Colors            NVARCHAR(16)     NOT NULL CONSTRAINT DF_Card_Colors DEFAULT (N'C'),
        Layout            NVARCHAR(50)     NULL,
        ImageUrl          NVARCHAR(500)    NULL,

        PriceUsd          DECIMAL(12,2)    NULL,
        PriceUsdFoil      DECIMAL(12,2)    NULL,
        PriceEur          DECIMAL(12,2)    NULL,
        PriceEurFoil      DECIMAL(12,2)    NULL,
        PriceUpdatedUtc   DATETIME2(0)     NULL,

        IsActive          BIT              NOT NULL CONSTRAINT DF_Card_IsActive DEFAULT (1),
        CreatedUtc        DATETIME2(0)     NOT NULL CONSTRAINT DF_Card_CreatedUtc DEFAULT (SYSUTCDATETIME()),
        ModifiedUtc       DATETIME2(0)     NOT NULL CONSTRAINT DF_Card_ModifiedUtc DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_Card PRIMARY KEY CLUSTERED (CardId),
        CONSTRAINT UQ_Card_ScryfallId UNIQUE (ScryfallId),
        CONSTRAINT UQ_Card_Printing UNIQUE (SetCode, CollectorNumber),
        CONSTRAINT CK_Card_Cmc CHECK (Cmc >= 0)
    );

    /* Pretraga po imenu je najcesci upit; INCLUDE pokriva listu rezultata. */
    CREATE INDEX IX_Card_Name ON catalog.Card (Name)
        INCLUDE (SetCode, SetName, CollectorNumber, PriceEur, PriceEurFoil);

    CREATE INDEX IX_Card_SetCode ON catalog.Card (SetCode) INCLUDE (Name);

    PRINT 'Kreirana tabela catalog.Card';
END
GO

/*  Istorija cena: bez ovoga svako osvezavanje pregazi jucerasnju cenu i ne
    moze da se vidi da li je karta poskupela.                                 */
IF OBJECT_ID(N'catalog.PriceHistory', N'U') IS NULL
BEGIN
    CREATE TABLE catalog.PriceHistory
    (
        PriceHistoryId BIGINT        IDENTITY(1,1) NOT NULL,
        CardId         INT           NOT NULL,
        CapturedDate   DATE          NOT NULL,
        PriceEur       DECIMAL(12,2) NULL,
        PriceEurFoil   DECIMAL(12,2) NULL,

        CONSTRAINT PK_PriceHistory PRIMARY KEY CLUSTERED (CardId, CapturedDate),
        CONSTRAINT UQ_PriceHistory_Id UNIQUE (PriceHistoryId),
        CONSTRAINT FK_PriceHistory_Card FOREIGN KEY (CardId)
            REFERENCES catalog.Card (CardId) ON DELETE CASCADE
    );
    PRINT 'Kreirana tabela catalog.PriceHistory';
END
GO

/*  Kursevi: aplikacija ih je vukla sa API-ja pri svakom pokretanju. Ovde su
    trajni, pa maloprodajna cena moze da se racuna i u bazi.                  */
IF OBJECT_ID(N'catalog.ExchangeRate', N'U') IS NULL
BEGIN
    CREATE TABLE catalog.ExchangeRate
    (
        RateDate     DATE          NOT NULL,
        BaseCurrency NCHAR(3)      NOT NULL,
        QuoteCurrency NCHAR(3)     NOT NULL,
        Rate         DECIMAL(18,6) NOT NULL,
        SourceName   NVARCHAR(100) NULL,
        CreatedUtc   DATETIME2(0)  NOT NULL CONSTRAINT DF_ExchangeRate_CreatedUtc DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_ExchangeRate PRIMARY KEY CLUSTERED (RateDate, BaseCurrency, QuoteCurrency),
        CONSTRAINT CK_ExchangeRate_Rate CHECK (Rate > 0)
    );
    PRINT 'Kreirana tabela catalog.ExchangeRate';
END
GO

/*  Fallback kurs, da racunanje cena radi i pre prvog uspesnog preuzimanja.
    1 EUR = 117 / 0.92 RSD, isto kao DEFAULT_RATES u services/pricing.py.     */
IF NOT EXISTS (SELECT 1 FROM catalog.ExchangeRate WHERE BaseCurrency = N'EUR' AND QuoteCurrency = N'RSD')
BEGIN
    INSERT INTO catalog.ExchangeRate (RateDate, BaseCurrency, QuoteCurrency, Rate, SourceName)
    VALUES (CAST(N'2000-01-01' AS DATE), N'EUR', N'RSD', 127.173913, N'ugrađena podrazumevana vrednost');
END
GO
