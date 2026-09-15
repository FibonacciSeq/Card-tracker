/*  Card-tracker :: 13 - full-text indeks za pretragu (OPCIONO)

    Bez ovoga pretraga kataloga radi preko LIKE '%tekst%', sto nijedan indeks
    ne moze da ubrza - na 100k karata to je oko 400-700 ms po upitu, umesto
    12-38 ms koliko treba lokalnom SQLite FTS5 indeksu.

    Full-Text Search je opciona komponenta SQL Server-a. Ako nije instalirana,
    ova skripta nista ne radi i ispise uputstvo. Da se instalira: pokreni
    SQL Server Setup > Add features > Full-Text and Semantic Extractions.

    NAPOMENA: deo koji pravi indeks nije mogao da bude izvrsen na masini na
    kojoj je pisan (FTS nije bio dostupan) - proveri ishod posle pokretanja
    upitom na kraju skripte.                                                 */

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE CardTracker;
GO

IF CONVERT(INT, SERVERPROPERTY('IsFullTextInstalled')) <> 1
BEGIN
    PRINT '';
    PRINT '  Full-Text Search nije instaliran na ovoj instanci.';
    PRINT '  Pretraga kataloga će raditi preko LIKE (sporije).';
    PRINT '';
    PRINT '  Da ga dodaš: SQL Server Setup > Add features to an existing';
    PRINT '  instance > Full-Text and Semantic Extractions for Search,';
    PRINT '  pa ponovo pokreni ovu skriptu.';
    PRINT '';
END
ELSE
BEGIN
    PRINT 'Full-Text Search je dostupan - pravim katalog i indeks...';

    IF NOT EXISTS (SELECT 1 FROM sys.fulltext_catalogs WHERE name = N'CardTrackerFT')
    BEGIN
        EXEC (N'CREATE FULLTEXT CATALOG CardTrackerFT AS DEFAULT');
        PRINT '  Kreiran full-text katalog CardTrackerFT.';
    END

    IF NOT EXISTS (SELECT 1 FROM sys.fulltext_indexes WHERE object_id = OBJECT_ID(N'catalog.Card'))
    BEGIN
        /*  Full-text indeks trazi jedinstveni jednokolonski indeks bez NULL-ova. */
        EXEC (N'
            CREATE FULLTEXT INDEX ON catalog.Card
            (
                Name            LANGUAGE 1033,
                SetName         LANGUAGE 1033,
                TypeLine        LANGUAGE 1033,
                CollectorNumber LANGUAGE 1033
            )
            KEY INDEX PK_Card
            ON CardTrackerFT
            WITH (CHANGE_TRACKING = AUTO)
        ');
        PRINT '  Kreiran full-text indeks nad catalog.Card.';
        PRINT '  Popunjavanje ide u pozadini - vidi upit ispod.';
    END
    ELSE
    BEGIN
        PRINT '  Full-text indeks već postoji.';
    END
END
GO

/*  Provera stanja: 0 u koloni Populating znaci da je indeks spreman.        */
SELECT
    TableName       = OBJECT_NAME(fi.object_id),
    CatalogName     = fc.name,
    ChangeTracking  = fi.change_tracking_state_desc,
    PopulateStatus  = FULLTEXTCATALOGPROPERTY(fc.name, 'PopulateStatus'),
    ItemCount       = FULLTEXTCATALOGPROPERTY(fc.name, 'ItemCount')
FROM sys.fulltext_indexes AS fi
INNER JOIN sys.fulltext_catalogs AS fc
    ON fc.fulltext_catalog_id = fi.fulltext_catalog_id;
GO
