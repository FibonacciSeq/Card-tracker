/*  Card-tracker :: test - ceo tok od ucitavanja do isporuke

    Pokretati na praznoj (ili test) bazi. Svaki neuspeh baca gresku, pa
    sqlcmd -b vraca nenulti exit kod i SQL Agent korak pukne.                */

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE CardTracker;
GO

SET NOCOUNT ON;

DECLARE @Failures INT = 0;

/*  Mali assert helper: poredi ocekivano i dobijeno.                         */
DECLARE @Results TABLE (TestName NVARCHAR(200), Expected NVARCHAR(100), Actual NVARCHAR(100), Passed BIT);

PRINT '=== Čišćenje ===';
DELETE FROM sales.Allocation;
DELETE FROM sales.OrderLine;
DELETE FROM sales.CustomerOrder;
DELETE FROM sales.Customer;
DELETE FROM inv.StockMovement;
DELETE FROM inv.Stock;
DELETE FROM purchasing.ReorderRule;
DELETE FROM catalog.PriceHistory;
DELETE FROM catalog.Card;
DELETE FROM etl.LoadError;
DELETE FROM etl.LoadRun;
DELETE FROM staging.ScryfallCard;
DELETE FROM staging.StockImport;

/* ---------------------------------------------------------- 1. katalog -- */
PRINT '=== 1. Učitavanje kataloga ===';

INSERT INTO staging.ScryfallCard (ScryfallId, Name, SetCode, SetName, CollectorNumber, TypeLine, Rarity, Cmc, Colors, PriceEur, PriceEurFoil)
VALUES
    ('11111111-1111-1111-1111-111111111111', N'Lightning Bolt', N'LEB', N'Limited Edition Beta', N'161', N'Instant', N'common', N'1', N'R', N'250.00', N'900.00'),
    ('22222222-2222-2222-2222-222222222222', N'Lightning Bolt', N'MMA', N'Modern Masters',       N'129', N'Instant', N'common', N'1', N'R', N'2.50',   N'8.00'),
    ('33333333-3333-3333-3333-333333333333', N'Forest',         N'BLB', N'Bloomburrow',          N'280', N'Basic Land — Forest', N'common', N'0', N'', N'0.10', N'0.40'),
    ('44444444-4444-4444-4444-444444444444', N'Serra Angel',    N'BLB', N'Bloomburrow',          N'031', N'Creature — Angel', N'uncommon', N'5', N'W', N'1.20', N'4.00'),
    /* namerno neispravan red - mora da zavrsi u etl.LoadError */
    ('not-a-guid',                            N'Broken Card',   N'XXX', N'Nowhere',              N'1',   N'Instant', N'common', N'1', N'R', N'1.00', NULL);

DECLARE @RunId BIGINT;
EXEC etl.usp_StartLoadRun @JobName = N'TEST_CATALOG', @SourceName = N'test', @LoadRunId = @RunId OUTPUT;
EXEC catalog.usp_MergeScryfallStaging @LoadRunId = @RunId;

INSERT INTO @Results
SELECT N'Katalog: učitane 4 ispravne kartice', N'4', CAST(COUNT(*) AS NVARCHAR(100)), CASE WHEN COUNT(*) = 4 THEN 1 ELSE 0 END
FROM catalog.Card;

INSERT INTO @Results
SELECT N'Katalog: 1 red odbijen', N'1', CAST(COUNT(*) AS NVARCHAR(100)), CASE WHEN COUNT(*) = 1 THEN 1 ELSE 0 END
FROM etl.LoadError WHERE LoadRunId = @RunId;

INSERT INTO @Results
SELECT N'Katalog: istorija cena zapisana', N'4', CAST(COUNT(*) AS NVARCHAR(100)), CASE WHEN COUNT(*) = 4 THEN 1 ELSE 0 END
FROM catalog.PriceHistory;

/*  Ponovno pokretanje istog fajla ne sme da napravi duplikate. */
EXEC catalog.usp_MergeScryfallStaging @LoadRunId = NULL;

INSERT INTO @Results
SELECT N'Katalog: ponovni merge je idempotentan', N'4', CAST(COUNT(*) AS NVARCHAR(100)), CASE WHEN COUNT(*) = 4 THEN 1 ELSE 0 END
FROM catalog.Card;

DECLARE @BoltBeta INT = (SELECT CardId FROM catalog.Card WHERE SetCode = N'leb' AND CollectorNumber = N'161');
DECLARE @BoltMma  INT = (SELECT CardId FROM catalog.Card WHERE SetCode = N'mma' AND CollectorNumber = N'129');
DECLARE @Forest   INT = (SELECT CardId FROM catalog.Card WHERE Name = N'Forest');
DECLARE @Angel    INT = (SELECT CardId FROM catalog.Card WHERE Name = N'Serra Angel');

/* ------------------------------------------------------------ 2. zalihe -- */
PRINT '=== 2. Uvoz zaliha iz tabele ===';

INSERT INTO staging.StockImport (SourceRowNo, CardName, SetCode, CollectorNumber, Quantity, IsFoil, ConditionCode, UnitCostRsd)
VALUES
    (1, N'Lightning Bolt', N'MMA', N'129', N'10', N'Ne', N'NM',  N'200'),
    (2, N'Lightning Bolt', N'MMA', N'129', N'3',  N'Da', N'NM',  N'800'),
    (3, N'Forest',         N'BLB', N'280', N'40', N'Ne', N'NM',  N'20'),
    (4, N'Serra Angel',    N'BLB', N'031', N'2',  N'Ne', N'LP',  N'90'),
    (5, N'Black Lotus',    NULL,   NULL,   N'1',  N'Ne', N'NM',  N'999999'),   -- nema je u katalogu
    (6, N'Forest',         N'BLB', N'280', N'abc',N'Ne', N'NM',  N'20'),       -- kolicina nije broj
    (7, N'Forest',         N'BLB', N'280', N'5',  N'Ne', N'ZZZ', N'20');       -- nepoznato stanje

DECLARE @StockRun BIGINT;
EXEC etl.usp_StartLoadRun @JobName = N'TEST_STOCK', @SourceName = N'test.xlsx', @LoadRunId = @StockRun OUTPUT;
EXEC inv.usp_ImportStockStaging @LoadRunId = @StockRun, @Mode = N'DELTA';

INSERT INTO @Results
SELECT N'Zalihe: 4 reda primenjena', N'4', CAST(COUNT(*) AS NVARCHAR(100)), CASE WHEN COUNT(*) = 4 THEN 1 ELSE 0 END
FROM inv.Stock;

INSERT INTO @Results
SELECT N'Zalihe: 3 reda odbijena', N'3', CAST(COUNT(*) AS NVARCHAR(100)), CASE WHEN COUNT(*) = 3 THEN 1 ELSE 0 END
FROM etl.LoadError WHERE LoadRunId = @StockRun;

INSERT INTO @Results
SELECT N'Zalihe: svaka promena ima trag', N'4', CAST(COUNT(*) AS NVARCHAR(100)), CASE WHEN COUNT(*) = 4 THEN 1 ELSE 0 END
FROM inv.StockMovement WHERE MovementType = N'IMPORT';

INSERT INTO @Results
SELECT N'Zalihe: foil i non-foil su odvojeni', N'2', CAST(COUNT(*) AS NVARCHAR(100)), CASE WHEN COUNT(*) = 2 THEN 1 ELSE 0 END
FROM inv.Stock WHERE CardId = @BoltMma;

/* -------------------------------------------------------- 3. porudzbina -- */
PRINT '=== 3. Porudžbina i rezervacija ===';

INSERT INTO sales.Customer (FullName, Email) VALUES (N'Marko Marković', N'marko@example.com');
DECLARE @CustomerId INT = SCOPE_IDENTITY();

DECLARE @OrderId INT, @Line1 INT, @Line2 INT, @Line3 INT;
EXEC sales.usp_CreateOrder @CustomerId = @CustomerId, @OrderId = @OrderId OUTPUT;

/* 4 komada ima na stanju (10) */
EXEC sales.usp_AddOrderLine @OrderId = @OrderId, @CardId = @BoltMma, @Quantity = 4, @OrderLineId = @Line1 OUTPUT;
/* 50 Forest-a, a na stanju je 40 -> nepokriveno 10 */
EXEC sales.usp_AddOrderLine @OrderId = @OrderId, @CardId = @Forest,  @Quantity = 50, @OrderLineId = @Line2 OUTPUT;
/* Beta Bolt - nema ga uopste na stanju */
EXEC sales.usp_AddOrderLine @OrderId = @OrderId, @CardId = @BoltBeta, @Quantity = 1, @OrderLineId = @Line3 OUTPUT;

INSERT INTO @Results
SELECT N'Porudžbina: cena uzeta iz cenovnika', N'>0',
       CAST(ISNULL(UnitPriceRsd, 0) AS NVARCHAR(100)),
       CASE WHEN ISNULL(UnitPriceRsd, 0) > 0 THEN 1 ELSE 0 END
FROM sales.OrderLine WHERE OrderLineId = @Line1;

DECLARE @Lines INT, @Pieces INT;
EXEC sales.usp_AllocateStock @OrderId = @OrderId, @AllocatedLines = @Lines OUTPUT, @AllocatedPieces = @Pieces OUTPUT;

INSERT INTO @Results
SELECT N'Rezervacija: 4 + 40 = 44 komada', N'44', CAST(@Pieces AS NVARCHAR(100)), CASE WHEN @Pieces = 44 THEN 1 ELSE 0 END;

INSERT INTO @Results
SELECT N'Rezervacija: Forest stavka delimično pokrivena', N'40',
       CAST(QuantityAllocated AS NVARCHAR(100)),
       CASE WHEN QuantityAllocated = 40 THEN 1 ELSE 0 END
FROM sales.OrderLine WHERE OrderLineId = @Line2;

INSERT INTO @Results
SELECT N'Rezervacija: Beta Bolt ostao nepokriven', N'0',
       CAST(QuantityAllocated AS NVARCHAR(100)),
       CASE WHEN QuantityAllocated = 0 THEN 1 ELSE 0 END
FROM sales.OrderLine WHERE OrderLineId = @Line3;

INSERT INTO @Results
SELECT N'Zalihe: slobodno = stanje - rezervisano', N'6',
       CAST(QuantityAvailable AS NVARCHAR(100)),
       CASE WHEN QuantityAvailable = 6 THEN 1 ELSE 0 END
FROM inv.vw_StockOnHand WHERE CardId = @BoltMma AND IsFoil = 0;

/*  Rezervisana roba ne sme da se skine sa lagera. */
BEGIN TRY
    EXEC inv.usp_AdjustStock @CardId = @Forest, @QuantityDelta = -35, @MovementType = N'WRITEOFF';
    INSERT INTO @Results VALUES (N'Zaštita: otpis ispod rezervisanog odbijen', N'greška', N'prošlo', 0);
END TRY
BEGIN CATCH
    INSERT INTO @Results VALUES (N'Zaštita: otpis ispod rezervisanog odbijen', N'greška', N'greška', 1);
END CATCH

/* ----------------------------------------------------------- 4. nabavka -- */
PRINT '=== 4. Predlog nabavke ===';

/* Uvek drzi bar 5 Serra Angel, dopuni do 12 */
INSERT INTO purchasing.ReorderRule (CardId, IsFoil, MinQuantity, TargetQuantity)
VALUES (@Angel, 0, 5, 12);

INSERT INTO @Results
SELECT N'Nabavka: Forest manjak za kupce = 10', N'10',
       CAST(QuantityToOrder AS NVARCHAR(100)),
       CASE WHEN QuantityToOrder = 10 THEN 1 ELSE 0 END
FROM purchasing.vw_RestockSuggestion WHERE CardId = @Forest AND IsFoil = 0;

INSERT INTO @Results
SELECT N'Nabavka: Beta Bolt treba 1', N'1',
       CAST(QuantityToOrder AS NVARCHAR(100)),
       CASE WHEN QuantityToOrder = 1 THEN 1 ELSE 0 END
FROM purchasing.vw_RestockSuggestion WHERE CardId = @BoltBeta AND IsFoil = 0;

/* Serra Angel: na stanju 2, prag 5 -> dopuni do 12, znaci 10 */
INSERT INTO @Results
SELECT N'Nabavka: Serra Angel dopuna do cilja = 10', N'10',
       CAST(QuantityToOrder AS NVARCHAR(100)),
       CASE WHEN QuantityToOrder = 10 THEN 1 ELSE 0 END
FROM purchasing.vw_RestockSuggestion WHERE CardId = @Angel AND IsFoil = 0;

INSERT INTO @Results
SELECT N'Nabavka: pokrivene kartice se ne predlažu', N'0',
       CAST(QuantityToOrder AS NVARCHAR(100)),
       CASE WHEN QuantityToOrder = 0 THEN 1 ELSE 0 END
FROM purchasing.vw_RestockSuggestion WHERE CardId = @BoltMma AND IsFoil = 0;

/* ---------------------------------------------------------- 5. isporuka -- */
PRINT '=== 5. Isporuka ===';

EXEC sales.usp_DeliverOrderLine @OrderLineId = @Line1;   -- svih 4

INSERT INTO @Results
SELECT N'Isporuka: stanje 10 - 4 = 6', N'6',
       CAST(Quantity AS NVARCHAR(100)),
       CASE WHEN Quantity = 6 THEN 1 ELSE 0 END
FROM inv.Stock WHERE CardId = @BoltMma AND IsFoil = 0;

INSERT INTO @Results
SELECT N'Isporuka: zabeležena kao SALE', N'1', CAST(COUNT(*) AS NVARCHAR(100)),
       CASE WHEN COUNT(*) = 1 THEN 1 ELSE 0 END
FROM inv.StockMovement WHERE MovementType = N'SALE' AND QuantityDelta = -4;

INSERT INTO @Results
SELECT N'Isporuka: rezervacija oslobođena', N'0',
       CAST(ISNULL(SUM(Quantity), 0) AS NVARCHAR(100)),
       CASE WHEN ISNULL(SUM(Quantity), 0) = 0 THEN 1 ELSE 0 END
FROM sales.Allocation WHERE OrderLineId = @Line1 AND ReleasedUtc IS NULL;

/* ------------------------------------------------------------- rezultat -- */
PRINT '';
PRINT '=== REZULTAT ===';

SELECT
    Status = CASE WHEN Passed = 1 THEN N'  ok  ' ELSE N' PAO  ' END,
    TestName,
    Expected,
    Actual
FROM @Results
ORDER BY Passed, TestName;

SELECT @Failures = COUNT(*) FROM @Results WHERE Passed = 0;

DECLARE @Total INT = (SELECT COUNT(*) FROM @Results);
PRINT CONCAT(N'Ukupno: ', @Total, N', palo: ', @Failures);

IF @Failures > 0
    THROW 51000, N'Testovi nisu prošli.', 1;
GO
