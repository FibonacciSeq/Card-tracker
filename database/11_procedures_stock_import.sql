/*  Card-tracker :: 11 - uvoz zaliha iz Excel/CSV staginga

    Ovo zamenjuje rucnu proveru tabele. Redovi koji ne prolaze validaciju ne
    ruse posao - zavrse u etl.LoadError i mogu da se pregledaju u SSMS-u.    */

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE CardTracker;
GO

CREATE OR ALTER PROCEDURE inv.usp_ImportStockStaging
(
    @LoadRunId BIGINT = NULL,
    /*  ABSOLUTE = kolicina u fajlu je novo stanje (popis).
        DELTA    = kolicina u fajlu se dodaje na postojece (nova nabavka).   */
    @Mode      NVARCHAR(10) = N'DELTA'
)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    IF @Mode NOT IN (N'DELTA', N'ABSOLUTE')
    BEGIN
        THROW 50030, N'@Mode mora biti DELTA ili ABSOLUTE.', 1;
    END

    DECLARE @RowsRead INT, @Applied INT = 0, @Rejected INT = 0;

    IF @LoadRunId IS NULL
    BEGIN
        EXEC etl.usp_StartLoadRun @JobName = N'IMPORT_STOCK', @LoadRunId = @LoadRunId OUTPUT;
    END

    SELECT @RowsRead = COUNT(*) FROM staging.StockImport;

    /*  Razresi svaki red na kartu iz kataloga.
        Prvo tacno izdanje (set + broj), pa najjeftinije izdanje po imenu.   */
    IF OBJECT_ID(N'tempdb..#Resolved') IS NOT NULL DROP TABLE #Resolved;

    CREATE TABLE #Resolved
    (
        StagingId     BIGINT        NOT NULL,
        SourceRowNo   INT           NULL,
        CardId        INT           NULL,
        CardName      NVARCHAR(250) NULL,
        Quantity      INT           NULL,
        IsFoil        BIT           NULL,
        ConditionCode NVARCHAR(4)   NULL,
        LanguageCode  NVARCHAR(5)   NULL,
        Location      NVARCHAR(100) NULL,
        UnitCostRsd   DECIMAL(12,2) NULL,
        Problem       NVARCHAR(200) NULL
    );

    INSERT INTO #Resolved
        (StagingId, SourceRowNo, CardId, CardName, Quantity, IsFoil, ConditionCode, LanguageCode, Location, UnitCostRsd, Problem)
    SELECT
        s.StagingId,
        s.SourceRowNo,
        resolved.CardId,
        s.CardName,
        TRY_CONVERT(INT, NULLIF(LTRIM(RTRIM(s.Quantity)), N'')),
        etl.fn_TryBit(s.IsFoil),
        UPPER(ISNULL(NULLIF(LTRIM(RTRIM(s.ConditionCode)), N''), N'NM')),
        LOWER(ISNULL(NULLIF(LTRIM(RTRIM(s.LanguageCode)), N''), N'en')),
        ISNULL(NULLIF(LTRIM(RTRIM(s.Location)), N''), N'MAIN'),
        etl.fn_TryDecimal(s.UnitCostRsd),
        CASE
            WHEN NULLIF(LTRIM(RTRIM(s.CardName)), N'') IS NULL
                THEN N'Nedostaje naziv kartice'
            WHEN resolved.CardId IS NULL
                THEN N'Kartica nije pronađena u katalogu'
            WHEN TRY_CONVERT(INT, NULLIF(LTRIM(RTRIM(s.Quantity)), N'')) IS NULL
                THEN N'Količina nije broj'
            WHEN TRY_CONVERT(INT, s.Quantity) < 0
                THEN N'Količina je negativna'
            WHEN NOT EXISTS (SELECT 1 FROM inv.Condition
                             WHERE ConditionCode = UPPER(ISNULL(NULLIF(LTRIM(RTRIM(s.ConditionCode)), N''), N'NM')))
                THEN N'Nepoznata oznaka stanja kartice'
            ELSE NULL
        END
    FROM staging.StockImport AS s
    OUTER APPLY
    (
        SELECT TOP (1) c.CardId
        FROM catalog.Card AS c
        WHERE c.Name = LTRIM(RTRIM(s.CardName))
          AND
          (
              /* Tacno izdanje ako je dato. */
              (NULLIF(LTRIM(RTRIM(s.SetCode)), N'') IS NOT NULL
               AND NULLIF(LTRIM(RTRIM(s.CollectorNumber)), N'') IS NOT NULL
               AND c.SetCode = LOWER(LTRIM(RTRIM(s.SetCode)))
               AND c.CollectorNumber = LTRIM(RTRIM(s.CollectorNumber)))
              OR
              /* Inace bilo koje izdanje - najjeftinije prvo. */
              (NULLIF(LTRIM(RTRIM(s.SetCode)), N'') IS NULL
               OR NULLIF(LTRIM(RTRIM(s.CollectorNumber)), N'') IS NULL)
          )
        ORDER BY
            CASE WHEN c.SetCode = LOWER(LTRIM(RTRIM(s.SetCode))) THEN 0 ELSE 1 END,
            CASE WHEN c.PriceEur IS NULL OR c.PriceEur = 0 THEN 1 ELSE 0 END,
            c.PriceEur,
            c.CardId
    ) AS resolved;

    /*  Losi redovi -> tabela gresaka. */
    INSERT INTO etl.LoadError (LoadRunId, SourceRowNo, ErrorMessage, RawData)
    SELECT @LoadRunId, r.SourceRowNo, r.Problem,
           CONCAT(N'name=', r.CardName, N' qty=', r.Quantity, N' cond=', r.ConditionCode)
    FROM #Resolved AS r
    WHERE r.Problem IS NOT NULL;

    SET @Rejected = @@ROWCOUNT;

    /*  Dobre redove primeni kroz usp_AdjustStock, da svaki dobije trag u
        knjizi promena umesto tihog UPDATE-a.                                */
    DECLARE @StagingId BIGINT, @CardId INT, @Quantity INT, @IsFoil BIT,
            @ConditionCode NVARCHAR(4), @LanguageCode NVARCHAR(5),
            @Location NVARCHAR(100), @UnitCostRsd DECIMAL(12,2);

    DECLARE row_cursor CURSOR LOCAL FAST_FORWARD FOR
        SELECT StagingId, CardId, Quantity, IsFoil, ConditionCode, LanguageCode, Location, UnitCostRsd
        FROM #Resolved
        WHERE Problem IS NULL
        ORDER BY StagingId;

    OPEN row_cursor;
    FETCH NEXT FROM row_cursor INTO @StagingId, @CardId, @Quantity, @IsFoil,
                                    @ConditionCode, @LanguageCode, @Location, @UnitCostRsd;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        DECLARE @Delta INT = @Quantity;

        IF @Mode = N'ABSOLUTE'
        BEGIN
            DECLARE @Current INT =
            (
                SELECT ISNULL(SUM(Quantity), 0)
                FROM inv.Stock
                WHERE CardId = @CardId AND IsFoil = @IsFoil
                  AND ConditionCode = @ConditionCode AND LanguageCode = @LanguageCode
                  AND Location = @Location
            );
            SET @Delta = @Quantity - @Current;
        END

        IF @Delta <> 0
        BEGIN
            BEGIN TRY
                EXEC inv.usp_AdjustStock
                    @CardId        = @CardId,
                    @QuantityDelta = @Delta,
                    @MovementType  = N'IMPORT',
                    @IsFoil        = @IsFoil,
                    @ConditionCode = @ConditionCode,
                    @LanguageCode  = @LanguageCode,
                    @Location      = @Location,
                    @UnitCostRsd   = @UnitCostRsd,
                    @ReferenceType = N'IMPORT',
                    @ReferenceId   = @LoadRunId;

                SET @Applied = @Applied + 1;
            END TRY
            BEGIN CATCH
                INSERT INTO etl.LoadError (LoadRunId, SourceRowNo, ErrorMessage, RawData)
                VALUES (@LoadRunId, NULL, ERROR_MESSAGE(), CONCAT(N'stagingId=', @StagingId));
                SET @Rejected = @Rejected + 1;
            END CATCH
        END
        ELSE
        BEGIN
            SET @Applied = @Applied + 1;   -- vec tacno, nema sta da se menja
        END

        FETCH NEXT FROM row_cursor INTO @StagingId, @CardId, @Quantity, @IsFoil,
                                        @ConditionCode, @LanguageCode, @Location, @UnitCostRsd;
    END

    CLOSE row_cursor;
    DEALLOCATE row_cursor;

    DROP TABLE #Resolved;

    /* EXEC ne prima izraz kao vrednost parametra - prvo u promenljivu. */
    DECLARE @Status NVARCHAR(20) = CASE WHEN @Rejected = 0 THEN N'SUCCESS' ELSE N'PARTIAL' END;

    EXEC etl.usp_FinishLoadRun
        @LoadRunId    = @LoadRunId,
        @LoadStatus   = @Status,
        @RowsRead     = @RowsRead,
        @RowsUpdated  = @Applied,
        @RowsRejected = @Rejected;

    SELECT RowsRead = @RowsRead, Applied = @Applied, Rejected = @Rejected;
END
GO
