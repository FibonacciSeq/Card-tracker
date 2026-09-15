/*  Card-tracker :: 12 - SQL Server Agent posao

    Dva koraka, kao sto se vide u SSMS-u pod SQL Server Agent > Jobs:
      1. Katalog - preuzmi Scryfall podatke i osvezi cene
      2. Zalihe  - pokupi tabele iz drop foldera i upiši ih

    Oba koraka pozivaju Python (potreban je HTTP i citanje Excel-a), pa svaki
    zavrsi tako sto pozove odgovarajucu proceduru u bazi.

    PRE POKRETANJA podesi putanje ispod za svoj server.                      */

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE msdb;
GO

DECLARE @JobName    SYSNAME       = N'CardTracker - Dnevno osvežavanje';
DECLARE @PythonExe  NVARCHAR(400) = N'C:\Program Files\Python312\python.exe';
DECLARE @ProjectDir NVARCHAR(400) = N'C:\CardTracker';
DECLARE @DatabaseName SYSNAME     = N'CardTracker';

/*  Ponovo kreira posao od nule, da skripta moze da se pusti vise puta.      */
IF EXISTS (SELECT 1 FROM msdb.dbo.sysjobs WHERE name = @JobName)
BEGIN
    EXEC msdb.dbo.sp_delete_job @job_name = @JobName, @delete_unused_schedule = 1;
    PRINT 'Obrisan postojeći posao.';
END

EXEC msdb.dbo.sp_add_job
    @job_name           = @JobName,
    @enabled            = 1,
    @description        = N'Osvežava Scryfall katalog i uvozi zalihe iz drop foldera.',
    @category_name      = N'[Uncategorized (Local)]',
    @notify_level_eventlog = 2;   -- upiši u event log samo kad padne

/* ------------------------------------------------- korak 1: katalog ----- */
DECLARE @Step1 NVARCHAR(1000) =
    N'"' + @PythonExe + N'" -m tools.etl_scryfall --database ' + @DatabaseName;

EXEC msdb.dbo.sp_add_jobstep
    @job_name         = @JobName,
    @step_name        = N'1 - Osveži Scryfall katalog',
    @step_id          = 1,
    @subsystem        = N'CmdExec',
    @command          = @Step1,
    @database_name    = NULL,
    @on_success_action = 3,   -- idi na sledeći korak
    /*  Ako katalog padne, zalihe i dalje vredi uvesti - zato 3, ne 2.
        Posao ce biti oznacen kao neuspesan preko poslednjeg koraka.         */
    @on_fail_action   = 3,
    @retry_attempts   = 2,
    @retry_interval   = 10,   -- minuta
    @flags            = 0;

/* -------------------------------------------------- korak 2: zalihe ----- */
DECLARE @Step2 NVARCHAR(1000) =
    N'"' + @PythonExe + N'" -m tools.etl_stock --database ' + @DatabaseName;

EXEC msdb.dbo.sp_add_jobstep
    @job_name         = @JobName,
    @step_name        = N'2 - Uvezi zalihe iz drop foldera',
    @step_id          = 2,
    @subsystem        = N'CmdExec',
    @command          = @Step2,
    @on_success_action = 3,
    @on_fail_action   = 3,
    @retry_attempts   = 1,
    @retry_interval   = 5;

/* ------------------------------- korak 3: provera da li je sve proslo --- */
/*  Gleda etl.LoadRun i obara posao ako je neki od koraka prijavio gresku.
    Bez ovoga bi posao bio "zelen" iako su podaci odbijeni.                  */
DECLARE @Step3 NVARCHAR(MAX) = N'
DECLARE @Failed INT =
(
    SELECT COUNT(*)
    FROM etl.LoadRun
    WHERE StartedUtc >= DATEADD(HOUR, -6, SYSUTCDATETIME())
      AND LoadStatus = ''FAILED''
);

DECLARE @Rejected INT =
(
    SELECT ISNULL(SUM(RowsRejected), 0)
    FROM etl.LoadRun
    WHERE StartedUtc >= DATEADD(HOUR, -6, SYSUTCDATETIME())
);

IF @Failed > 0
    THROW 52000, N''Bar jedno učitavanje je palo - vidi etl.vw_RecentLoads.'', 1;

IF @Rejected > 0
    PRINT CONCAT(N''Upozorenje: odbijeno redova: '', @Rejected, N''. Vidi etl.LoadError.'');
';

EXEC msdb.dbo.sp_add_jobstep
    @job_name         = @JobName,
    @step_name        = N'3 - Provera rezultata učitavanja',
    @step_id          = 3,
    @subsystem        = N'TSQL',
    @command          = @Step3,
    @database_name    = @DatabaseName,
    @on_success_action = 1,   -- kraj, uspeh
    @on_fail_action   = 2;    -- kraj, neuspeh

/* ---------------------------------------------------------- raspored ---- */
EXEC msdb.dbo.sp_add_jobschedule
    @job_name       = @JobName,
    @name           = N'Svaki dan u 04:00',
    @freq_type      = 4,        -- dnevno
    @freq_interval  = 1,
    @active_start_time = 040000;

EXEC msdb.dbo.sp_add_jobserver @job_name = @JobName, @server_name = N'(LOCAL)';

PRINT 'Kreiran posao: ' + @JobName;
GO
