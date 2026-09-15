/*  Card-tracker :: 01 - baza i seme
    Idempotentno: moze da se pokrece vise puta.                              */

/*  Filtrirani indeksi i indeksirani pogledi zahtevaju ove opcije.
    SSMS ih podrazumevano ukljucuje, sqlcmd ne - zato eksplicitno.  */
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF DB_ID(N'CardTracker') IS NULL
BEGIN
    PRINT 'Kreiram bazu CardTracker...';
    EXEC (N'CREATE DATABASE CardTracker');
END
GO

ALTER DATABASE CardTracker SET RECOVERY SIMPLE;
GO

USE CardTracker;
GO

/*  Seme razdvajaju odgovornosti:
      catalog - referentni podaci sa Scryfall-a (sta karta jeste)
      inv     - zalihe (sta imamo)
      sales   - kupci i porudzbine (sta dugujemo)
      purchasing - pravila nabavke (sta treba da naručimo)
      staging - sirovi ucitani podaci, pre validacije
      etl     - istorija ucitavanja i greske                                  */

DECLARE @schemas TABLE (name SYSNAME);
INSERT INTO @schemas (name) VALUES (N'catalog'), (N'inv'), (N'sales'), (N'purchasing'), (N'staging'), (N'etl');

DECLARE @name SYSNAME, @sql NVARCHAR(200);
DECLARE schema_cursor CURSOR LOCAL FAST_FORWARD FOR SELECT name FROM @schemas;

OPEN schema_cursor;
FETCH NEXT FROM schema_cursor INTO @name;

WHILE @@FETCH_STATUS = 0
BEGIN
    IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = @name)
    BEGIN
        SET @sql = N'CREATE SCHEMA ' + QUOTENAME(@name);
        EXEC sys.sp_executesql @sql;
        PRINT 'Kreirana šema: ' + @name;
    END
    FETCH NEXT FROM schema_cursor INTO @name;
END

CLOSE schema_cursor;
DEALLOCATE schema_cursor;
GO
