/*  Card-tracker :: 10 - ucitavanje podataka (ono sto posao poziva)          */

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE CardTracker;
GO

CREATE OR ALTER PROCEDURE etl.usp_StartLoadRun
(
    @JobName    NVARCHAR(100),
    @SourceName NVARCHAR(400) = NULL,
    @LoadRunId  BIGINT        = NULL OUTPUT
)
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO etl.LoadRun (JobName, SourceName) VALUES (@JobName, @SourceName);
    SET @LoadRunId = SCOPE_IDENTITY();
END
GO


CREATE OR ALTER PROCEDURE etl.usp_FinishLoadRun
(
    @LoadRunId    BIGINT,
    @LoadStatus   NVARCHAR(20),
    @RowsRead     INT = 0,
    @RowsInserted INT = 0,
    @RowsUpdated  INT = 0,
    @RowsRejected INT = 0,
    @Message      NVARCHAR(2000) = NULL
)
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE etl.LoadRun
    SET FinishedUtc  = SYSUTCDATETIME(),
        LoadStatus   = @LoadStatus,
        RowsRead     = @RowsRead,
        RowsInserted = @RowsInserted,
        RowsUpdated  = @RowsUpdated,
        RowsRejected = @RowsRejected,
        Message      = @Message
    WHERE LoadRunId = @LoadRunId;
END
GO


/*  staging.ScryfallCard -> catalog.Card

    MERGE po ScryfallId. Cene se upisuju samo ako su stvarno stigle, da
    prazna vrednost u fajlu ne obrise jucerasnju cenu.                       */
CREATE OR ALTER PROCEDURE catalog.usp_MergeScryfallStaging
(
    @LoadRunId BIGINT = NULL
)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @RowsRead INT, @Inserted INT = 0, @Updated INT = 0, @Rejected INT = 0;
    DECLARE @ChangeLog TABLE (Action NVARCHAR(10));

    /*  Bez prosledjenog run-a otvaramo sopstveni: svaka odbijena linija mora
        da bude vezana za neko ucitavanje, inace se gubi.                    */
    DECLARE @OwnsRun BIT = 0;

    IF @LoadRunId IS NULL
    BEGIN
        EXEC etl.usp_StartLoadRun @JobName = N'MERGE_SCRYFALL', @LoadRunId = @LoadRunId OUTPUT;
        SET @OwnsRun = 1;
    END

    SELECT @RowsRead = COUNT(*) FROM staging.ScryfallCard;

    /*  Redovi bez upotrebljivog kljuca idu u greske, ne ruse posao.         */
    INSERT INTO etl.LoadError (LoadRunId, ErrorMessage, RawData)
    SELECT @LoadRunId,
           N'Neispravan ili nedostajući ScryfallId / Name / SetCode',
           CONCAT(N'id=', s.ScryfallId, N' name=', s.Name, N' set=', s.SetCode)
    FROM staging.ScryfallCard AS s
    WHERE TRY_CONVERT(UNIQUEIDENTIFIER, s.ScryfallId) IS NULL
       OR NULLIF(LTRIM(RTRIM(s.Name)), N'') IS NULL
       OR NULLIF(LTRIM(RTRIM(s.SetCode)), N'') IS NULL;

    SET @Rejected = @@ROWCOUNT;

    /*  Jedan red po ScryfallId - duplikat u fajlu bi oborio MERGE. */
    WITH Clean AS
    (
        SELECT
            ScryfallId      = TRY_CONVERT(UNIQUEIDENTIFIER, s.ScryfallId),
            Name            = LTRIM(RTRIM(s.Name)),
            SetCode         = LOWER(LTRIM(RTRIM(s.SetCode))),
            SetName         = ISNULL(LTRIM(RTRIM(s.SetName)), N''),
            CollectorNumber = ISNULL(LTRIM(RTRIM(s.CollectorNumber)), N''),
            TypeLine        = s.TypeLine,
            Rarity          = s.Rarity,
            Cmc             = ISNULL(TRY_CONVERT(DECIMAL(6,2), s.Cmc), 0),
            Colors          = ISNULL(NULLIF(s.Colors, N''), N'C'),
            Layout          = s.Layout,
            ImageUrl        = s.ImageUrl,
            PriceUsd        = etl.fn_TryDecimal(s.PriceUsd),
            PriceUsdFoil    = etl.fn_TryDecimal(s.PriceUsdFoil),
            PriceEur        = etl.fn_TryDecimal(s.PriceEur),
            PriceEurFoil    = etl.fn_TryDecimal(s.PriceEurFoil),
            rn = ROW_NUMBER() OVER (PARTITION BY TRY_CONVERT(UNIQUEIDENTIFIER, s.ScryfallId)
                                    ORDER BY s.StagingId DESC)
        FROM staging.ScryfallCard AS s
        WHERE TRY_CONVERT(UNIQUEIDENTIFIER, s.ScryfallId) IS NOT NULL
          AND NULLIF(LTRIM(RTRIM(s.Name)), N'') IS NOT NULL
          AND NULLIF(LTRIM(RTRIM(s.SetCode)), N'') IS NOT NULL
    )
    MERGE catalog.Card AS target
    USING (SELECT * FROM Clean WHERE rn = 1) AS source
        ON target.ScryfallId = source.ScryfallId
    WHEN MATCHED THEN
        UPDATE SET
            target.Name            = source.Name,
            target.SetCode         = source.SetCode,
            target.SetName         = source.SetName,
            target.CollectorNumber = source.CollectorNumber,
            target.TypeLine        = source.TypeLine,
            target.Rarity          = source.Rarity,
            target.Cmc             = source.Cmc,
            target.Colors          = source.Colors,
            target.Layout          = source.Layout,
            target.ImageUrl        = ISNULL(source.ImageUrl, target.ImageUrl),
            target.PriceUsd        = ISNULL(source.PriceUsd,     target.PriceUsd),
            target.PriceUsdFoil    = ISNULL(source.PriceUsdFoil, target.PriceUsdFoil),
            target.PriceEur        = ISNULL(source.PriceEur,     target.PriceEur),
            target.PriceEurFoil    = ISNULL(source.PriceEurFoil, target.PriceEurFoil),
            target.PriceUpdatedUtc = CASE WHEN source.PriceEur IS NOT NULL
                                            OR source.PriceUsd IS NOT NULL
                                          THEN SYSUTCDATETIME() ELSE target.PriceUpdatedUtc END,
            target.IsActive        = 1,
            target.ModifiedUtc     = SYSUTCDATETIME()
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (ScryfallId, Name, SetCode, SetName, CollectorNumber, TypeLine, Rarity,
                Cmc, Colors, Layout, ImageUrl, PriceUsd, PriceUsdFoil, PriceEur, PriceEurFoil,
                PriceUpdatedUtc)
        VALUES (source.ScryfallId, source.Name, source.SetCode, source.SetName,
                source.CollectorNumber, source.TypeLine, source.Rarity, source.Cmc,
                source.Colors, source.Layout, source.ImageUrl, source.PriceUsd,
                source.PriceUsdFoil, source.PriceEur, source.PriceEurFoil, SYSUTCDATETIME())
    OUTPUT $action INTO @ChangeLog;

    SELECT @Inserted = SUM(CASE WHEN Action = N'INSERT' THEN 1 ELSE 0 END),
           @Updated  = SUM(CASE WHEN Action = N'UPDATE' THEN 1 ELSE 0 END)
    FROM @ChangeLog;

    /*  Snimi dnevnu cenu, da istorija ostane i posle sledeceg osvezavanja.  */
    MERGE catalog.PriceHistory AS target
    USING
    (
        SELECT CardId, CAST(SYSUTCDATETIME() AS DATE) AS CapturedDate, PriceEur, PriceEurFoil
        FROM catalog.Card
        WHERE PriceEur IS NOT NULL OR PriceEurFoil IS NOT NULL
    ) AS source
        ON target.CardId = source.CardId AND target.CapturedDate = source.CapturedDate
    WHEN MATCHED THEN
        UPDATE SET target.PriceEur = source.PriceEur, target.PriceEurFoil = source.PriceEurFoil
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (CardId, CapturedDate, PriceEur, PriceEurFoil)
        VALUES (source.CardId, source.CapturedDate, source.PriceEur, source.PriceEurFoil);

    DECLARE @Status NVARCHAR(20) = CASE WHEN @Rejected = 0 THEN N'SUCCESS' ELSE N'PARTIAL' END;

    EXEC etl.usp_FinishLoadRun
        @LoadRunId    = @LoadRunId,
        @LoadStatus   = @Status,
        @RowsRead     = @RowsRead,
        @RowsInserted = @Inserted,
        @RowsUpdated  = @Updated,
        @RowsRejected = @Rejected;

    SELECT RowsRead = @RowsRead, Inserted = @Inserted, Updated = @Updated, Rejected = @Rejected;
END
GO
