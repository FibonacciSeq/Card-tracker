/*  Card-tracker :: 06 - funkcije

    Maloprodajna logika je do sada zivela samo u services/pricing.py, pa je
    baza nije mogla da primeni. Ovde je ista pravila ima i SQL.               */

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE CardTracker;
GO

/*  Najsvezije poznat kurs EUR -> RSD.                                       */
CREATE OR ALTER FUNCTION catalog.fn_CurrentEurToRsd ()
RETURNS DECIMAL(18,6)
AS
BEGIN
    RETURN
    (
        SELECT TOP (1) Rate
        FROM catalog.ExchangeRate
        WHERE BaseCurrency = N'EUR' AND QuoteCurrency = N'RSD'
        ORDER BY RateDate DESC
    );
END
GO

/*  Prodajna cena u dinarima: kurs + marza po cenovnom rangu, zaokruzeno na
    10 navise. Pragovi i mnozioci se poklapaju sa calculate_card_price_rsd.

    Pisano kao jedan RETURN CASE da bi SQL Server mogao da je inline-uje
    (skalarne UDF u WHERE/SELECT nad milion redova inace bole).

    Racuna se u DECIMAL-u, ne u FLOAT-u, pa nema greske zaokruzivanja koju
    Python verzija ima na 20 EUR (2860.0000000000005 -> 2870).                */
CREATE OR ALTER FUNCTION catalog.fn_RetailPriceRsd
(
    @PriceEur DECIMAL(12,2),
    @EurToRsd DECIMAL(18,6)
)
RETURNS INT
AS
BEGIN
    RETURN
    (
        SELECT CASE
            WHEN @PriceEur IS NULL OR @PriceEur <= 0 THEN 0
            WHEN @PriceEur < 0.35 THEN 50          -- fiksni pod za sitnice
            ELSE CAST(CEILING(
                     CASE
                         WHEN @PriceEur <   2.00 THEN @PriceEur * @EurToRsd + 15
                         WHEN @PriceEur <   5.00 THEN @PriceEur * @EurToRsd + 30
                         WHEN @PriceEur <  10.00 THEN @PriceEur * @EurToRsd + 60
                         WHEN @PriceEur <  25.00 THEN @PriceEur * @EurToRsd * 1.10
                         WHEN @PriceEur <  50.00 THEN @PriceEur * @EurToRsd * 1.07
                         WHEN @PriceEur < 100.00 THEN @PriceEur * @EurToRsd * 1.05
                         ELSE                         @PriceEur * @EurToRsd * 1.03
                     END / 10.0) * 10 AS INT)
        END
    );
END
GO

/*  Ista cena, korigovana za stanje kartice (NM 100%, LP 85%, ...).          */
CREATE OR ALTER FUNCTION inv.fn_RetailPriceForCondition
(
    @PriceEur      DECIMAL(12,2),
    @EurToRsd      DECIMAL(18,6),
    @ConditionCode NVARCHAR(4)
)
RETURNS INT
AS
BEGIN
    RETURN
    (
        SELECT CAST(CEILING(
                   catalog.fn_RetailPriceRsd(@PriceEur, @EurToRsd)
                   * ISNULL((SELECT PriceFactor FROM inv.Condition WHERE ConditionCode = @ConditionCode), 1.0)
                   / 10.0) * 10 AS INT)
    );
END
GO

/*  Bezbedna konverzija teksta u broj: ulaz iz staginga nije proveren, a
    TRY_CONVERT vraca NULL umesto da obori ceo posao.                        */
CREATE OR ALTER FUNCTION etl.fn_TryDecimal (@Value NVARCHAR(64))
RETURNS DECIMAL(12,2)
AS
BEGIN
    RETURN TRY_CONVERT(DECIMAL(12,2), NULLIF(LTRIM(RTRIM(REPLACE(@Value, N',', N'.'))), N''));
END
GO

/*  "Da"/"Yes"/"1"/"true" -> 1. Excel fajlovi dolaze u svim varijantama.     */
CREATE OR ALTER FUNCTION etl.fn_TryBit (@Value NVARCHAR(16))
RETURNS BIT
AS
BEGIN
    RETURN CASE
        WHEN LOWER(LTRIM(RTRIM(ISNULL(@Value, N'')))) IN (N'1', N'da', N'yes', N'y', N'true', N't', N'foil')
        THEN 1 ELSE 0
    END;
END
GO
