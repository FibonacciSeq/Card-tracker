/*  Card-tracker :: 07 - pogledi (ono sto se gleda u SSMS-u)                 */

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE CardTracker;
GO

/*  Karta sa maloprodajnom cenom u dinarima, obicna i foil.                  */
CREATE OR ALTER VIEW catalog.vw_CardPrice
AS
SELECT
    c.CardId,
    c.Name,
    c.SetCode,
    c.SetName,
    c.CollectorNumber,
    c.Rarity,
    c.PriceEur,
    c.PriceEurFoil,
    catalog.fn_RetailPriceRsd(c.PriceEur,     catalog.fn_CurrentEurToRsd()) AS RetailRsd,
    catalog.fn_RetailPriceRsd(c.PriceEurFoil, catalog.fn_CurrentEurToRsd()) AS RetailFoilRsd,
    c.PriceUpdatedUtc
FROM catalog.Card AS c
WHERE c.IsActive = 1;
GO

/*  Zalihe sa slobodnom kolicinom.
    Available = na stanju - vec rezervisano za kupce. Ovo je broj koji sme
    da se obeca novom kupcu.                                                 */
CREATE OR ALTER VIEW inv.vw_StockOnHand
AS
SELECT
    s.StockId,
    s.CardId,
    c.Name,
    c.SetCode,
    c.SetName,
    c.CollectorNumber,
    s.IsFoil,
    s.ConditionCode,
    s.LanguageCode,
    s.Location,
    s.Quantity                                   AS QuantityOnHand,
    ISNULL(a.QuantityAllocated, 0)               AS QuantityAllocated,
    s.Quantity - ISNULL(a.QuantityAllocated, 0)  AS QuantityAvailable,
    s.UnitCostRsd,
    inv.fn_RetailPriceForCondition(
        CASE WHEN s.IsFoil = 1 THEN c.PriceEurFoil ELSE c.PriceEur END,
        catalog.fn_CurrentEurToRsd(),
        s.ConditionCode)                         AS UnitRetailRsd
FROM inv.Stock AS s
INNER JOIN catalog.Card AS c
    ON c.CardId = s.CardId
OUTER APPLY
(
    SELECT SUM(al.Quantity) AS QuantityAllocated
    FROM sales.Allocation AS al
    WHERE al.StockId = s.StockId
      AND al.ReleasedUtc IS NULL
) AS a;
GO

/*  Vrednost lagera po kartici.                                              */
CREATE OR ALTER VIEW inv.vw_StockValue
AS
SELECT
    v.CardId,
    v.Name,
    v.SetCode,
    v.SetName,
    SUM(v.QuantityOnHand)                          AS TotalQuantity,
    SUM(v.QuantityAvailable)                       AS TotalAvailable,
    SUM(v.QuantityOnHand * v.UnitRetailRsd)        AS RetailValueRsd,
    SUM(v.QuantityOnHand * ISNULL(v.UnitCostRsd, 0)) AS CostValueRsd
FROM inv.vw_StockOnHand AS v
GROUP BY v.CardId, v.Name, v.SetCode, v.SetName;
GO

/*  Neispunjena potraznja: sta su kupci trazili a jos nije rezervisano.      */
CREATE OR ALTER VIEW sales.vw_OpenDemand
AS
SELECT
    ol.OrderLineId,
    o.OrderId,
    o.CustomerId,
    cu.FullName                                   AS CustomerName,
    o.PlacedUtc,
    ol.CardId,
    c.Name,
    c.SetCode,
    ol.IsFoil,
    ol.ConditionCode,
    ol.QuantityOrdered,
    ol.QuantityAllocated,
    ol.QuantityOrdered - ol.QuantityAllocated     AS QuantityOutstanding,
    ol.UnitPriceRsd
FROM sales.OrderLine AS ol
INNER JOIN sales.CustomerOrder AS o
    ON o.OrderId = ol.OrderId
INNER JOIN sales.Customer AS cu
    ON cu.CustomerId = o.CustomerId
INNER JOIN catalog.Card AS c
    ON c.CardId = ol.CardId
WHERE o.OrderStatus IN (N'OPEN', N'PARTIAL')
  AND ol.QuantityOrdered > ol.QuantityAllocated;
GO

/*  Predlog nabavke - ovo zamenjuje rucno poredjenje u Excel-u.

    Kolicina se uzima kao veca od dve potrebe:
      1. nepokrivena potraznja kupaca (moram nekome da isporucim)
      2. dopuna do ciljne zalihe ako je palo ispod praga (hocu da imam na lageru)

    Karta se pojavljuje u rezultatu samo ako je nesto stvarno potrebno.       */
CREATE OR ALTER VIEW purchasing.vw_RestockSuggestion
AS
WITH Demand AS
(
    SELECT CardId, IsFoil, SUM(QuantityOutstanding) AS QuantityNeeded
    FROM sales.vw_OpenDemand
    GROUP BY CardId, IsFoil
),
Available AS
(
    SELECT CardId, IsFoil, SUM(QuantityAvailable) AS QuantityAvailable
    FROM inv.vw_StockOnHand
    GROUP BY CardId, IsFoil
),
Universe AS
(
    SELECT CardId, IsFoil FROM Demand
    UNION
    SELECT CardId, IsFoil FROM Available
    UNION
    SELECT CardId, IsFoil FROM purchasing.ReorderRule WHERE IsActive = 1
)
SELECT
    u.CardId,
    c.Name,
    c.SetCode,
    c.SetName,
    c.CollectorNumber,
    u.IsFoil,
    sh.QuantityAvailable,
    sh.QuantityNeeded                              AS QuantityCustomerDemand,
    r.MinQuantity,
    r.TargetQuantity,
    sh.ShortfallForOrders,
    sh.ShortfallForStockLevel,
    /* Naruci onoliko koliko pokriva obe potrebe. */
    CASE WHEN sh.ShortfallForOrders > sh.ShortfallForStockLevel
         THEN sh.ShortfallForOrders
         ELSE sh.ShortfallForStockLevel
    END                                            AS QuantityToOrder,
    catalog.fn_RetailPriceRsd(
        CASE WHEN u.IsFoil = 1 THEN c.PriceEurFoil ELSE c.PriceEur END,
        catalog.fn_CurrentEurToRsd())              AS UnitRetailRsd
FROM Universe AS u
INNER JOIN catalog.Card AS c
    ON c.CardId = u.CardId
LEFT JOIN Demand AS d
    ON d.CardId = u.CardId AND d.IsFoil = u.IsFoil
LEFT JOIN Available AS av
    ON av.CardId = u.CardId AND av.IsFoil = u.IsFoil
LEFT JOIN purchasing.ReorderRule AS r
    ON r.CardId = u.CardId AND r.IsFoil = u.IsFoil AND r.IsActive = 1
CROSS APPLY
(
    SELECT
        QuantityAvailable = ISNULL(av.QuantityAvailable, 0),
        QuantityNeeded    = ISNULL(d.QuantityNeeded, 0),
        ShortfallForOrders =
            CASE WHEN ISNULL(d.QuantityNeeded, 0) > ISNULL(av.QuantityAvailable, 0)
                 THEN ISNULL(d.QuantityNeeded, 0) - ISNULL(av.QuantityAvailable, 0)
                 ELSE 0 END,
        ShortfallForStockLevel =
            CASE WHEN r.ReorderRuleId IS NOT NULL
                  AND ISNULL(av.QuantityAvailable, 0) < r.MinQuantity
                 THEN r.TargetQuantity - ISNULL(av.QuantityAvailable, 0)
                 ELSE 0 END
) AS sh;
GO

/*  Poslednja ucitavanja, za brzi pogled u SSMS-u.                           */
CREATE OR ALTER VIEW etl.vw_RecentLoads
AS
SELECT TOP (200)
    lr.LoadRunId,
    lr.JobName,
    lr.SourceName,
    lr.StartedUtc,
    lr.FinishedUtc,
    DATEDIFF(SECOND, lr.StartedUtc, ISNULL(lr.FinishedUtc, SYSUTCDATETIME())) AS DurationSeconds,
    lr.LoadStatus,
    lr.RowsRead,
    lr.RowsInserted,
    lr.RowsUpdated,
    lr.RowsRejected,
    lr.Message
FROM etl.LoadRun AS lr
ORDER BY lr.StartedUtc DESC;
GO
