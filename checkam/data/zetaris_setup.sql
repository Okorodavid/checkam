-- CheckAm's reference data as Zetaris tables. `python -m checkam zetaris` runs these one statement at a time.
-- Each source is a public JSON file in this repository, registered as a Lightning REST table, then
-- flattened into a view CheckAm queries with SQL.

CREATE LIGHTNING DATABASE CHECKAM_REST DESCRIBE BY "CheckAm reference data";

CREATE SCHEMASTORE CONTAINER checkam;

CREATE LIGHTNING REST TABLE official_src FROM CHECKAM_REST REQUEST(
    endpoint "https://raw.githubusercontent.com/Okorodavid/checkam/main/checkam/data/official.json",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
) BODY ();

CREATE SCHEMASTORE VIEW official_accounts WITH CONTAINER checkam AS
SELECT o.name AS name, o.kind AS kind, concat_ws('|', o.aliases) AS aliases,
       concat_ws('|', o.domains) AS domains, concat_ws('|', o.x) AS x_handles
FROM checkam_rest.official_src
LATERAL VIEW explode(orgs) AS o;

CREATE LIGHTNING REST TABLE regulators_src FROM CHECKAM_REST REQUEST(
    endpoint "https://raw.githubusercontent.com/Okorodavid/checkam/main/checkam/data/regulators.json",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
) BODY ();

CREATE SCHEMASTORE VIEW regulator_warnings WITH CONTAINER checkam AS
SELECT w.name AS name, concat_ws('|', w.aliases) AS aliases, w.regulator AS regulator, w.finding AS finding, w.url AS url
FROM checkam_rest.regulators_src
LATERAL VIEW explode(warned) AS w;

CREATE SCHEMASTORE VIEW regulator_rules WITH CONTAINER checkam AS
SELECT r.id AS id, r.`when` AS topic, r.regulator AS regulator, r.finding AS finding, r.url AS url
FROM checkam_rest.regulators_src
LATERAL VIEW explode(rules) AS r;

CREATE LIGHTNING REST TABLE sec_notices_src FROM CHECKAM_REST REQUEST(
    endpoint "https://raw.githubusercontent.com/Okorodavid/checkam/main/checkam/data/sec_notices.json",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
) BODY ();

CREATE SCHEMASTORE VIEW sec_notices WITH CONTAINER checkam AS
SELECT n.alias AS alias, n.name AS name, n.title AS title, n.url AS url, n.regulator AS regulator
FROM checkam_rest.sec_notices_src
LATERAL VIEW explode(notices) AS n;
