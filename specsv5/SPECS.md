# SPECS — RELEASE R5 — Specificație reconciliată cu implementarea

> **Identificator unic de release: R5** — același pe SPECS.md,
> schema_starter.sql, roles.sql și suita de teste (istoric intern:
> R1=v1–v3/design, R2=primul review extern, R3=al doilea, R4=al treilea,
> R5=închiderea review-ului v5).
> Baseline „as-built”, reconciliat la 19 iulie 2026 cu aplicația Django din
> acest repository. Schema de referință este în `specsv5/schema_starter.sql`,
> rolurile în `specsv5/roles.sql`, iar suita PostgreSQL/RLS în
> `specsv5/test_rls.sh`. La conflict, migrările Django și schema instalată au
> prioritate pentru structura deja implementată; acest document descrie
> regulile de business și arhitectura curentă.

---

## 1. Ce construim

Platformă colaborativă între o firmă de contabilitate și firmele sale
cliente: colectarea, organizarea, verificarea și trasabilitatea documentelor
contabile primare, ÎNAINTE de introducerea în programul de contabilitate
(SAGA). Poziționare: document collection and accounting workflow management.
NU program de contabilitate; integrarea SAGA nu e în MVP.

**Conceptul central: dosarul contabil lunar** (`perioada_contabila`) —
documentele, checklist-ul cu ce era așteptat, conversațiile, predările
fizice și starea procesării, toate legate de aceeași perioadă.

---

## 2. Modelul de tenant și acces (v4 — corectat)

Ierarhie: **firmă de contabilitate → firme cliente → perioade → documente**.

În interfață și în documentația pentru utilizatori folosim termenul **firmă
de contabilitate**. Identificatorii existenți din baza de date și din cod
(`cabinet_id`, `cabinete_contabilitate`, `admin_cabinet`) rămân neschimbați
pentru compatibilitate și sunt tratați ca termeni tehnici interni.

- Un **membru intern** (`admin_cabinet`, `contabil_coordonator`, `contabil`)
  aparține exact unei firme de contabilitate (`utilizatori.cabinet_id NOT NULL`).
- Un **utilizator client** (`client_admin`, `client_operator`) NU aparține
  niciunei firme de contabilitate (`cabinet_id NULL`); accesul lui vine exclusiv din
  alocările `utilizator_firma`.
- **Superuserul platformei** are rol distinct: `superuser_platforma` —
  singurul care poate avea `is_staff`/`is_superuser` (CHECK-ul din schemă
  leagă strict rol ↔ flag-uri ↔ firma de contabilitate; combinațiile parțiale ca
  `is_staff` fără `is_superuser` sunt respinse de DB). Nu aparține
  niciunei firme de contabilitate și nu poate fi alocat la firme cliente (trigger).
- **Accesul efectiv la o firmă** = alocare directă în `utilizator_firma`
  SAU (pentru `admin_cabinet` și `contabil_coordonator`) apartenența firmei
  la firma de contabilitate proprie. Regula e implementată în funcția SQL
  `fn_firmele_utilizatorului()`, folosită de toate politicile RLS. Politica
  `SELECT` pe `firme` exprimă suplimentar direct ramura firmei de contabilitate pentru
  admin/coordonator, astfel încât `INSERT ... RETURNING` folosit de ORM să
  poată returna rândul nou în același statement.
- Coerența între tenanturi este garantată de trigger: un membru intern nu
  poate fi alocat la o firmă clientă a altei firme de contabilitate.

| Rol | Vede | Poate |
|---|---|---|
| `admin_cabinet` | toate firmele cliente ale firmei de contabilitate | creează/editează firme, gestionează utilizatori și alocări (prin service layer), configurează checklist-uri, redeschide perioade |
| `contabil_coordonator` | toate firmele cliente ale firmei de contabilitate | tot ce poate contabilul, pe orice firmă clientă a tenantului |
| `contabil` | firmele alocate | verifică, cere clarificări, acceptă, marchează procesat, închide perioade |
| `client_admin` | firmele alocate | încarcă, confirmă luna, cere invitarea de operatori (prin service layer) |
| `client_operator` | firmele alocate | încarcă documente, comentează și înregistrează predări; nu modifică checklist-ul |

**Administrarea utilizatorilor, alocărilor și invitațiilor** (decizia D2):
aceste scrieri NU sunt posibile prin conexiunea web (`app_user` nu are
GRANT). Ele trec prin service layer, pe conexiunea privilegiată, cu
verificare de rol în aplicație + scriere în `audit_log`.

**REGULĂ DE SECURITATE (critică)**: conexiunea privilegiată ocolește RLS,
deci:
- **doar superuserul platformei** primește acces la Django Admin-ul
  privilegiat; `admin_cabinet` NU primește NICIODATĂ acces la el;
- **design concret** (R5): Admin-ul platformei rulează ca **instanță
  separată** — `config/settings/admin.py`, în care `default` ESTE
  conexiunea privilegiată — deployată pe alt hostname/port, restricționată
  de rețea. Aplicația principală nu montează deloc Django Admin. ATENȚIE:
  Django Admin acceptă implicit orice utilizator activ cu `is_staff=true`
  (`AdminSite.has_permission` NU cere superuser) — de aceea instanța
  folosește un **`AdminSite` custom** cu
  `has_permission = request.user.is_active and request.user.is_superuser`,
  iar CHECK-ul din DB garantează oricum că doar `superuser_platforma`
  poate avea aceste flag-uri;
- ecranele de administrare ale firmei de contabilitate (`admin_cabinet`) rulează pe
  conexiunea normală (protejate de RLS) și apelează serviciile privilegiate
  DOAR pentru operațiile punctuale de scriere (creare utilizator, alocare,
  invitație), fiecare serviciu verificând explicit, în cod: rolul
  apelantului + apartenența țintei la firma de contabilitate a apelantului;
- serviciile privilegiate nu returnează niciodată date interogate liber pe
  conexiunea privilegiată către UI — citirile se fac pe conexiunea normală.

**Invitații** (`invitatii`): ciclu de viață complet — creată (token hash,
expirare 7 zile) → acceptată / anulată / expirată. Retrimiterea = anularea
celei vechi + creare nouă. Invitațiile interne au `cabinet_id`, cele de
client au `firma_id`.

---

## 3. Tipuri de document și checklist (v4 — semantică corectată)

Nomenclator `tipuri_document` (seed în schemă): factura, aviz_expeditie,
bon_consum, nir, extras_cont, chitanta, registru_casa, comanda.

**Compatibilitate document–cont** (`tipuri_cont_compatibile`):
- `extras_cont` → conturi de tip `banca`, `card`
- `registru_casa` → conturi de tip `casa`

**Generarea checklist-ului** (`fn_genereaza_checklist_perioada`, testată):
- DOAR configurările `activ=true` cu `obligatoriu=true` generează cerințe
- tipurile cu cont financiar generează un rând per cont activ COMPATIBIL
- documentele opționale (`obligatoriu=false`) pot fi încărcate oricând,
  dar nu apar ca „lipsă"
- `frecventa` (`lunar`/`ocazional`/`zilnic`) e informativă în MVP;
  `termen_predare_zi` servește reminder-elor per-tip (faza 2); termenul
  perioadei e `perioade_contabile.termen_predare`
- funcția e idempotentă și returnează numărul total de cerințe create

**Statusurile cerinței**: `lipsa` (nimic încărcat), `partial` (există
documente dar nu toate — setat manual, opțional cu
`numar_documente_declarat`), `primit`, `nu_se_aplica` (clientul declară
explicit „nu există luna asta", cu observație).

**Sincronizarea checklist–documente** (în service layer, nu în DB):
- primul document `trimis` pe un (tip, cont) → cerința `lipsa` devine `partial`
- clientul sau contabilul poate marca manual `primit`
- anularea/ștergerea ultimului document al unei cerințe → revine la `lipsa`
- reclasificarea unui document (alt tip) → recalculează ambele cerințe

**Modificarea conturilor financiare în timpul lunii** (service layer):
- cont nou activat → serviciul reapelează `fn_genereaza_checklist_perioada`
  pentru perioadele deschise ale firmei (funcția e idempotentă — adaugă
  doar rândurile noi)
- cont dezactivat → cerințele lui aflate în `lipsa` devin `nu_se_aplica`
  cu observație automată („cont dezactivat la <data>"); cerințele care au
  deja documente rămân neatinse

---

## 4. Mașinile de stare (complete)

### 4.1 Document

| Din | Acțiune | În | Cine | Precondiții | Efecte |
|---|---|---|---|---|---|
| — | încărcare | `draft` | client, contabil | perioadă neînchisă | creare document + fișiere |
| `draft` | trimitere | `trimis` | cel care l-a creat | are ≥1 fișier activ | notifică contabilul; actualizează cerința |
| `draft` | anulare | `anulat` | cel care l-a creat | — | |
| `trimis` | preluare | `in_verificare` | contabil | — | |
| `trimis` | anulare | `anulat` | client_admin, autorul documentului, contabil | — | actualizează cerința |
| `in_verificare` | acceptare | `acceptat` | contabil | metadatele minime completate (§5) | păstrează cerința sincronizată; `primit` rămâne o confirmare manuală, deoarece o categorie poate conține multe documente și mai multe serii de upload |
| `in_verificare` | cere clarificări | `necesita_clarificari` | contabil | mesaj obligatoriu | notifică clientul; perioada → `documente_incomplete` dacă era confirmată |
| `in_verificare` | anulare | `anulat` | contabil | motiv obligatoriu | |
| `necesita_clarificari` | reîncărcare/răspuns | `trimis` | client | fișier nou sau comentariu | reintră în coadă; notifică contabilul |
| `necesita_clarificari` | anulare | `anulat` | client_admin, autorul documentului, contabil | — | |
| `acceptat` | marcare procesat | `procesat` | contabil | — | |
| `acceptat` | retur în verificare | `in_verificare` | contabil | motiv | corectură de flux |
| `procesat` | arhivare | `arhivat` | sistem | la închiderea perioadei | document imutabil |

Stări finale: `arhivat`, `anulat`. Anularea NU e posibilă din `acceptat`,
`procesat`, `arhivat` (acolo: retur + anulare, auditat). Ștergerea logică
(soft-delete) e permisă doar pentru `draft`, de către autor.

### 4.2 Perioadă

| Din | Acțiune | În | Cine | Precondiții | Efecte |
|---|---|---|---|---|---|
| — | deschidere lunară | `deschisa` | contabil / contabil coordonator | nu există deja | generează checklist; deschiderea automată nu este implementată |
| `deschisa` | confirmare client | `gata_pentru_verificare` | client_admin | TOATE cerințele în `primit` sau `nu_se_aplica` (`lipsa` ȘI `partial` blochează — „am transmis toate documentele" înseamnă toate) | `confirmata_de_client_la`; notifică contabilul; documentele ulterioare primesc `incarcat_dupa_confirmare` |
| `gata_pentru_verificare` | începe verificarea | `in_lucru` | contabil | — | |
| `in_lucru` / `gata_pentru_verificare` | cere clarificări (≥1 doc) | `documente_incomplete` | contabil | — | notifică clientul |
| `documente_incomplete` | toate clarificările rezolvate | `in_lucru` | sistem | niciun doc în `necesita_clarificari` | notifică contabilul |
| `in_lucru` | cere închiderea | `inchidere_in_curs` | contabil | TOATE documentele în `procesat`, `anulat` sau `arhivat` (arhivatele provin dintr-o închidere anterioară — cazul redeschiderii); TOATE cerințele în `primit`/`nu_se_aplica`; nicio digitizare `in_lucru` și niciun fișier inbox în `in_asteptare`/`disponibil` | blochează editarea și programează arhiva lunară după commit |
| `inchidere_in_curs` | publică arhiva verificată | `inchisa` | sistem/worker | toate copiile și manifestul au checksum valid | `procesat`→`arhivat`; `inchisa_la/de`; notifică clientul |
| `inchidere_in_curs` | eșec definitiv arhivă | `in_lucru` | sistem/worker | 3 încercări epuizate | deblochează luna; istoric + audit cu eroarea |
| `inchisa` | redeschidere | `in_lucru` | admin_cabinet, contabil_coordonator | motiv obligatoriu | documentele `arhivat` RĂMÂN arhivate; se pot adăuga documente noi; audit obligatoriu |

Toate tranzițiile trec prin servicii (`perioade/services.py`,
`documente/services.py`) care validează tabelele de mai sus, scriu
`istoric_stari` + `audit_log` și emit notificările. Update de stare
direct din view = interzis.

---

## 5. Introducerea metadatelor și sugestia AI

- **Clientul** completează la upload doar: tip document (+ cont financiar
  unde se cere) și, opțional, o notă.
- **Contabilul**, la acceptare, completează metadatele contabile: partener
  (căutare + creare inline în `parteneri`), direcție, serie, număr, date,
  valori. Pentru `factura`/`chitanta`/`aviz_expeditie`, acceptarea cere
  minim: partener + serie + număr (altfel `uq_doc_business` nu poate
  proteja). Pentru `extras_cont`: doar contul (setat deja la upload).
- Duplicatele: `IntegrityError` pe `uq_doc_business` → mesaj prietenos cu
  link către documentul existent.
- **Inboxul necategorizat** poate primi o sugestie AI pentru tip, cont și
  direcție. Sugestia nu creează documente și nu schimbă stări contabile.
  Contabilul trebuie să confirme, să corecteze sau să ignore explicit, iar
  decizia finală este auditată. Fără cheie/provider, același formular rămâne
  complet utilizabil manual.
- **Extragerea structurată** sugerează pentru documentele aflate în verificare:
  emitent/destinatar și CUI, serie, număr, data documentului/scadenței, monedă,
  net, TVA și total. Schema providerului este strictă, iar serviciul
  normalizează datele/moneda/zecimalele, elimină valorile invalide și
  semnalează neconcordanțe de total, scadență sau CUI. Formularul poate fi
  precompletat, dar contabilul confirmă sau corectează explicit; se păstrează
  fingerprint-ul fișierelor sursă, sugestia, valorile finale, providerul,
  modelul, promptul, actorul și momentul revizuirii. După trei erori se
  continuă manual. Cu `DOCUMENT_AI_ENABLED=false` nu se creează joburi de
  extracție structurată și nu se face niciun apel extern.
- **Administrarea partenerilor**: listă per firmă (contabil), creare inline
  din formularul de acceptare, dezactivare (nu ștergere). Faza 2: verificare
  CUI la ANAF.

---

## 6. Stack tehnic

| Componentă | Alegere |
|---|---|
| Framework | **Django 5.2 LTS** + Django Templates; Gunicorn/WhiteNoise în producție |
| Limbaj | Python 3.12+ |
| DB | PostgreSQL 16+ |
| Lucru în fundal | comenzi Django; cozi PostgreSQL pentru procesare, citire/AI, extracție, arhive și exporturi; `launchd` opțional pe macOS |
| Storage | backend propriu local sau Cloudflare R2 prin `boto3`, cu URL-uri semnate |
| PDF | PyMuPDF (validare, text, preview, separare, pagini, thumbnail) |
| Imagini | Pillow |
| OCR local | Tesseract 5, limbi `ron+eng` |
| AI documente | adaptor propriu OpenAI Responses / DeepSeek-compatible Chat Completions; coadă PostgreSQL |
| Email | backend-ul Django console în local; SMTP configurabil prin variabile de mediu |
| Testare | pytest + pytest-django |
| Calitate | ruff + ruff format; comandă automată `release_readiness` |

---

## 7. Autentificare și Django (decis, fail-closed în R5)

- **Contractul concret pentru `AUTH_USER_MODEL`**: modelul `Utilizator` din
  aplicația `conturi` moștenește `AbstractBaseUser`, **fără
  `PermissionsMixin`** (permisiunile granulare nu intră în MVP), și este
  mapat pe tabela existentă `utilizatori` prin `db_table`/`db_column`
  explicite. Are `USERNAME_FIELD = "email"`, `EMAIL_FIELD = "email"`,
  `REQUIRED_FIELDS = ["nume"]`, câmpul `password` mapat pe
  `parola_hash`, iar `is_active` pe `activ`. Coloanele `last_login`,
  `is_staff`, `is_superuser` există în schemă. Modelul există în starea
  Django încă din prima migrare `conturi`, prin `SeparateDatabaseAndState`;
  SQL-ul din `core.0001` rămâne sursa structurii fizice.
- **Managerul** este `UtilizatorManager(BaseUserManager)`. `create_user()`
  normalizează emailul la lowercase și nu acceptă flag-uri privilegiate;
  `create_superuser()` impune simultan `rol="superuser_platforma"`,
  `is_staff=true`, `is_superuser=true`, `cabinet_id=NULL` și rulează numai
  prin management command/Admin-ul platformei pe conexiunea privilegiată.
- Fără `PermissionsMixin` nu există câmpuri/tabele `groups` sau
  `user_permissions`. `has_perm()` și `has_module_perms()` întorc `true`
  exclusiv pentru un utilizator activ cu `is_superuser=true`; formularele
  `UserCreationForm`/`UserChangeForm` și `ModelAdmin` sunt implementări
  custom pentru aceste câmpuri. Aceasta este și politica de autorizare a
  modelelor din Admin, suplimentar față de gate-ul `AdminSite` din §2.
- **Superuser-ul platformei**: `is_superuser=true` + `is_staff=true`;
  folosește Django Admin prin conexiunea privilegiată (§8).
- **Autentificarea rulează integral pe conexiunea privilegiată** (R5 —
  închide vizibilitatea globală a tabelei `utilizatori` pe web):
  - backend de autentificare custom: atât `authenticate()` (login), cât și
    `get_user()` (încărcarea utilizatorului de sesiune la fiecare request)
    citesc valorile necesare prin `using("privileged")`, dar returnează un
    obiect `Utilizator` rehidratat și legat explicit de aliasul `default`;
    un obiect ORM citit direct de pe `privileged` NU este pus în
    `request.user`;
  - `config/db_routers.py` este fail-closed: orice citire/scriere ORM fără
    `.using(...)` merge la `default`, inclusiv `request.user.save()` și
    obiectele noi care îl primesc ca FK. Numai serviciile privilegiate pot
    folosi explicit `.using("privileged")` și
    `transaction.atomic(using="privileged")`. Astfel, rutarea „sticky” a
    instanțelor Django nu poate transforma o scriere obișnuită într-una cu
    BYPASSRLS;
  - politica RLS de SELECT pe `utilizatori` e restrictivă: rândul propriu +
    colegii din firma de contabilitate + utilizatorii firmelor accesibile;
    fără identitate
    = zero rânduri;
  - coloana `parola_hash` e **revocată de la SELECT** pentru `app_user`
    (grant pe listă de coloane); managerul implicit al modelului face
    `defer("password")` pe web — codul care uită primește „permission
    denied for column", eșec zgomotos, nu scurgere;
  - `last_login`: receiver-ul standard e dezactivat; se scrie prin
    `using("privileged")` (web nu are UPDATE pe coloană deloc);
  - **resetarea parolei** și **acceptarea invitației**:
    `conturi/services.py::seteaza_parola(user, parola)` pe privileged;
  - schimbarea parolei de către utilizatorul AUTENTIFICAT rămâne pe web
    (UPDATE-ul coloanei `parola_hash` pe rândul propriu e permis; se
    folosește `save(update_fields=["password"])` — fără SELECT pe coloană).
- **Teste obligatorii de rutare DB**: se capturează aliasul real al
  interogărilor și se verifică faptul că `request.user._state.db ==
  "default"`, `request.user.save()` scrie pe `default`, un obiect nou cu FK
  spre `request.user` scrie tot pe `default`, iar scrierea pe `privileged`
  este posibilă numai când serviciul o cere explicit. Un test negativ
  interzice orice router care cade implicit pe aliasul instanței.
- **Normalizare**: email lowercase la salvare (unicitatea e pe
  `lower(email)` în DB); CUI fără spații, regulă unică pentru prefixul RO
  aleasă la implementare; serie/număr: trim + uppercase.

---

## 8. Baza de date, conexiuni și RLS (v4 — corectat și testat)

### Bootstrap — sursă unică de adevăr (D7, revizuit)

1. **Provisioning (o dată per cluster, de infrastructură)**: `specsv5/roles.sql`
   creează rolurile NOLOGIN `app_user`/`app_admin` și rolurile de login
   (`migrare` = owner-ul bazei, `web_app`, `worker`). Necesită CREATEROLE —
   de aceea NU face parte din migrări.
2. **Migrarea `core.0001`** rulează conținutul de bootstrap din
   `specsv5/schema_starter.sql` prin
   `migrations.RunSQL`. Fișierul NU conține `BEGIN`/`COMMIT` (Django
   deschide tranzacția migrării; `BEGIN`/`COMMIT` explicite în RunSQL
   strică starea tranzacției — avertisment documentat Django).
3. Migrările rulează **întotdeauna cu rolul `migrare`** (owner). Motiv
   dublu: (a) `ALTER DEFAULT PRIVILEGES` se leagă de rolul care creează
   obiectele — dacă o migrare viitoare rulează cu alt rol, tabelele ei nu
   primesc granturile; (b) owner-ul nu are nevoie de CREATEROLE.
4. Fișierul SQL devine imutabil după primul deploy. **Orice schimbare
   ulterioară = migrare Django nouă.** Modelele existente se declară cu
   `SeparateDatabaseAndState` (state only), `db_table`/`db_column` explicite.

**Convenții pentru migrările viitoare**:
- orice tabel de business nou primește, ÎN ACEEAȘI migrare: RLS + politici
  pe operații (altfel e vizibil integral prin `app_user`);
- `app_user` NU primește DELETE nici pe tabelele viitoare (default
  privileges fără DELETE — decizia D9); tabelele tehnice care au nevoie
  (ex: `django_session`) primesc `GRANT DELETE` explicit, punctual, în
  migrarea care le creează;
- `app_admin` primește `USAGE, SELECT` pe secvențele existente și viitoare,
  necesare tabelelor tehnice Django cu `BigAutoField`; `app_user` nu primește
  automat acces la secvențe.

### Conexiuni și roluri

Trei roluri de login (create EFECTIV de `specsv5/roles.sql`, cu parole din
variabile psql — nu exemple comentate):

- **`web_app`** (alias Django `default`) → membru în `app_user`, fără
  BYPASSRLS — tot traficul web.
- **`worker`** (alias Django `privileged`) → **cu atributul BYPASSRLS
  propriu**, membru în `app_admin` — management commands, serviciile
  administrative și de autentificare, Admin-ul superuserului.
- **`migrare`** → owner-ul bazei; exclusiv pentru migrări. **Ca owner,
  ocolește RLS pe tabelele proprii (decizia D10)** — de aceea nu se
  folosește niciodată pentru trafic de aplicație.

CAPCANĂ documentată: `BYPASSRLS` este atribut de rol și **nu se moștenește**
prin `IN ROLE` — rolul de login al worker-ului trebuie să-l aibă direct.

### Deciziile de securitate RLS (v6)

- **D10 — ENABLE, nu FORCE**: tabelele au `ENABLE ROW LEVEL SECURITY`,
  fără `FORCE`. Motivul, verificat pe topologia reală: cu `FORCE`, owner-ul
  non-superuser `migrare` (a) nu-și poate insera seed-ul și (b) funcțiile
  `SECURITY DEFINER` pe care le deține intră în recursie infinită
  (politicile lor interoghează tabele tot cu politici → stack depth
  exceeded). Cu `ENABLE`, owner-ul ocolește RLS prin design — acceptabil,
  pentru că `migrare` rulează doar migrări; rolurile aplicației nu sunt
  niciodată owner.
- **D11 — blindarea funcțiilor DEFINER**: toate au
  `SET search_path = public, pg_temp` (pg_temp ULTIMUL — altfel un
  utilizator poate crea tabele temporare cu aceleași nume și ocoli
  izolarea; pg_temp e implicit primul pentru relații), nume de tabele
  calificate cu schema și `EXECUTE` revocat de la PUBLIC.
- **Limită asumată, documentată onest**: identitatea RLS e un parametru
  custom (`app.utilizator_id`) pe care orice client SQL cu acces la
  conexiunea web îl poate seta. RLS-ul protejează împotriva filtrelor ORM
  uitate și a bug-urilor de aplicație — NU e o graniță de securitate
  împotriva SQL-ului arbitrar executat direct pe conexiune. Apărarea la
  acel nivel: aplicația nu expune SQL brut, secretele conexiunilor stau în
  secret manager, iar operațiile sensibile au granturile revocate
  structural (acelea rezistă și la SQL arbitrar).

### Cum se setează identitatea RLS (corectat în v3.1)

`ATOMIC_REQUESTS` NU acoperă middleware-ul, deci middleware-ul deschide EL
tranzacția. ATENȚIE (blocaje găsite la review): Django convertește
excepțiile view-ului — INCLUSIV `Http404` și `PermissionDenied` — în
răspunsuri HTTP înainte ca ele să ajungă la middleware; blocul `atomic()`
ar ieși normal și ar face COMMIT pentru un 500, un 404 sau un 403. Decizie:
**rollback pe ORICE răspuns cu status ≥ 400** (un view care scrie și apoi
răspunde cu eroare nu are ce comite; view-urile nu returnează niciodată
4xx „intenționat" după scrieri — anti-pattern interzis prin convenție):

```python
class RLSMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)
        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cur:
                cur.execute(
                    "SELECT set_config('app.utilizator_id', %s, true)",
                    [str(request.user.pk)],
                )
            response = self.get_response(request)
            if isinstance(response, StreamingHttpResponse) and not getattr(
                response, "rls_safe_streaming", False
            ):
                transaction.set_rollback(True, using="default")
                raise RuntimeError(
                    "StreamingHttpResponse autentificat nu este suportat"
                )
            if response.status_code >= 400:
                # Http404/PermissionDenied/erorile au fost deja convertite
                # în răspuns; fără marcare explicită, tranzacția s-ar COMITE
                transaction.set_rollback(True, using="default")
        return response
```

- Se plasează DUPĂ `AuthenticationMiddleware`. `ATOMIC_REQUESTS = False`.
- Încărcarea user-ului de sesiune NU mai depinde de SELECT-ul web pe
  `utilizatori` — backend-ul de autentificare citește pe privileged (§7).
- Middleware-ul marchează rollback pentru orice răspuns cu status ≥ 400.
  Un `StreamingHttpResponse` autentificat este respins implicit; numai un
  flux marcat explicit `rls_safe_streaming`, care nu mai interoghează baza
  în timpul iterării, este permis. Testele Django curente acoperă protecția
  streaming. Scenariile de rollback 500/404/403 și lipsa scurgerii identității
  între request-uri rămân verificări obligatorii pentru auditul de release.
- Connection pooling extern (pgbouncer): doar în mod `transaction`.

### Provisioning-ul rolurilor (R5)

`specsv5/roles.sql` se rulează **ca superuser** — crearea unui rol cu
`BYPASSRLS` cere superuser, nu doar `CREATEROLE` (regulă PostgreSQL).
Fișierul are `\set ON_ERROR_STOP on` și reconciliază un profil exact, nu doar
atributele necesare imediat: elimină `SUPERUSER`, `CREATEDB`, `CREATEROLE`,
`REPLICATION` și `LOGIN` unde sunt interzise; `BYPASSRLS` rămâne exclusiv
pe `worker`; rolurile de grup rămân `NOLOGIN`. Revocă orice membership care
implică cele cinci roluri și nu este unul dintre cele două permise
(`web_app → app_user`, `worker → app_admin`), apoi recreează exact aceste
două relații fără `ADMIN OPTION`. Blocul final verifică toate atributele și
absența membership-urilor suplimentare. Parolele se setează doar la creare;
rotația rămâne o operațiune separată prin secret manager.

### Ce garantează schema (validat prin teste pe topologia reală — §14)

- fără identitate setată → zero rânduri din orice tabel de tenant,
  **inclusiv `utilizatori`**; `parola_hash` e nelizibilă pe web chiar și
  cu identitate (coloană revocată)
- contabilul vede doar firmele alocate; admin/coordonator — toate firmele
  cliente ale firmei de contabilitate;
  utilizatorii vizibili = doar cei din tenant
- izolare completă între firmele de contabilitate; tabelele temporare nu pot ocoli
  izolarea (pg_temp)
- auto-alocarea și orice scriere în utilizatori/alocări/invitații prin
  conexiunea web → respinse structural (granturi revocate)
- parola/profilul altui utilizator nu pot fi modificate prin web;
  `last_login` nu poate fi scris deloc pe web
- scrierile pe firme neaccesibile → respinse de `WITH CHECK`
- crearea/editarea firmelor: doar `admin_cabinet`, doar în firma de
  contabilitate proprie
- audit-ul nu poate referi firme neaccesibile; `audit_log` și
  `istoric_stari` sunt append-only pentru `app_user`; legătura polimorfică
  din `istoric_stari` este validată de trigger, deci entitatea trebuie să
  existe și să aparțină aceleiași firme
- lanțul de înlocuire a fișierelor e legat de același document (FK compus)
- responsabilul unei perioade: membru intern al firmei de contabilitate; `contabil` —
  obligatoriu alocat firmei (trigger)
- doar `superuser_platforma` poate avea `is_staff`/`is_superuser`;
  combinațiile parțiale sunt respinse de CHECK; nu se alocă la firme
- alocările au coerență completă rol ↔ rol_in_firma (trigger)
- invitațiile au rol↔ancoră↔rol_in_firma coerente și finalitate unică
- upload intents: doar pe firmele accesibile, doar în nume propriu, legate
  obligatoriu de un document; cheia și expirarea sunt generate de DB,
  ținta opțională a înlocuirii este legată prin FK compus de același
  document, rândul nu poate fi actualizat de `app_user`, iar un intent poate
  produce cel mult un fișier
- `retentie_ani` este NULL sau minimum 5 ani; o extensie per document nu
  poate scurta termenul legal; tabelele viitoare rămân fără DELETE pentru
  `app_user`
- extragerile structurate, arhivele lunare și intrările manifestului sunt
  vizibile numai în tenantul propriu; `app_user` nu le poate fabrica sau
  modifica, iar FK-urile compuse interzic surse din altă firmă/perioadă;
  stările `in_lucru` cer lease coerent și revizuirea extracției cere actor + dată

RLS e plasa de siguranță, nu scuza: filtrele explicite pe firmă se scriu
oricum în ORM.

---

## 9. Fișiere și pipeline (v4 — model complet)

**Semantică (D6)**: un document = un obiect contabil; `fisiere_document` =
paginile/versiunile lui. La fiecare serie, clientul alege explicit între
„fiecare fișier este un document separat” și „toate fișierele formează un
singur document”. Un upload cu N facturi creează astfel N documente, iar
fotografiile mai multor pagini ale aceleiași facturi rămân fișiere ale unui
singur document. Seriile pot fi repetate până la închiderea perioadei, au cel
mult 500 de fișiere și sunt trimise atomic; contabilul primește o singură
notificare pentru întreaga serie. Un PDF din inbox poate primi sugestii de
separare, dar nu este separat fără confirmarea explicită a contabilului.

**Câmpuri de pipeline** pe fișier: `stare_procesare`
(`in_asteptare`/`in_lucru`/`procesat`/`eroare`), `eroare_procesare`,
`incercari_procesare`, `procesare_inceputa_la`, `thumbnail_key`,
`inlocuieste_fisier_id` (lanț de
versiuni, FK compus — nu poate traversa firmele), `sters_la/sters_de`
(soft-delete și pe fișiere). Distincție de nume: `numar_pagini` = câte
pagini are fișierul (calculat de pipeline); `ordine` = poziția fișierului
în cadrul documentului (afișare).

**Inbox pentru încărcare multiplă**: un lot necategorizat nu creează
documente `draft`. `loturi_incarcare` leagă seria de exact o firmă și o
perioadă contabilă, iar `fisiere_inbox` păstrează câte un original, uploaderul,
numele, dimensiunea și checksum-ul. Triggerul DB generează o cheie temporară
`clients/<firma>/<AAAA-LL>/_temp/<lot>/<fisier>.part`; după verificarea
extensiei, MIME-ului și magic bytes, serviciul privilegiat copiază și verifică
SHA-256 înainte de a publica originalul în
`clients/<firma>/<AAAA-LL>/inbox/<lot>/originals/<fisier>`. Intențiile
temporare expiră după 24h, iar `cleanup_inbox_uploads` elimină obiectele
abandonate. Originalele validate pot fi descărcate numai după verificarea RLS,
printr-o adresă semnată cu expirare scurtă. Publicarea creează idempotent un
rând în `analize_fisiere_inbox`; planul complet este în
`docs/BULK_INBOX_AND_MONTH_ARCHIVE.md`.

**Analiză și clasificare asistată**: `analize_fisiere_inbox` păstrează separat
starea procesării (`in_asteptare`/`in_lucru`/`finalizata`/`eroare`), lease-ul,
maximum 3 încercări, providerul, modelul, versiunea promptului, tipul/contul/
direcția sugerate, încrederea, rezumatul, dovezile și consumul de tokeni.
`process_document_analyses` execută mai întâi citirea locală și apoi, opțional,
coada AI. Fiecare PDF este tratat pe pagini: textul încorporat suficient este
folosit direct, iar paginile scanate și imaginile sunt citite cu Tesseract
`ron+eng`. OpenAI primește PDF-ul ca file input sau imaginea ca image input;
adaptorul DeepSeek primește textul local paginat, inclusiv rezultatul OCR.

`pagini_fisiere_inbox` păstrează numărul paginii, metoda, textul extras,
checksum-ul și cheia preview-ului privat. `limite_sugerate` poate veni dintr-o
euristică conservatoare sau din providerul AI. Contabilul trebuie să confirme
intervale complete, ordonate, fără goluri sau suprapuneri. Serviciul de separare
creează câte un document/fișier derivat per interval, iar
`derivari_fisiere_inbox` păstrează sursa imuabilă, intervalul, metoda, actorul și
checksum-urile sursei și derivatului. Imaginile pot produce un singur interval.

Rezultatul providerului este neîncrezător față de instrucțiunile din document,
este validat față de tipurile și conturile configurate în tenant și nu are
drept de scriere în documentele contabile. Revizuirea contabilului salvează
`confirmata`, `corectata`, `segmentata` sau `ignorata`, identitatea și momentul deciziei,
valorile finale și, la clasificare, legătura spre documentul creat. Originalul
inbox rămâne imuabil și verificat din nou prin SHA-256 înainte de copiere.
RLS permite rolului web doar SELECT tenant-scoped asupra analizelor; workerul
privilegiat execută procesarea și serviciul reverifică rolul/apartenența înainte
de orice confirmare. `DOCUMENT_AI_ENABLED=false` este implicit și garantează
că nu se face niciun apel extern fără configurare explicită.

**Extracție structurată și revizuire**:
`extractii_structurate_documente` este legată de document, firmă, perioadă și
fișierul principal, iar `fisiere_sursa` + `checksum_sursa` fixează versiunea
tuturor fișierelor active folosite. Coada are lease de 15 minute, maximum trei
încercări și recuperare pentru rândurile `in_lucru` abandonate. Rezultatul
păstrează `campuri_sugerate`, avertismentele, încrederea și metadatele
providerului; revizuirea păstrează `confirmata`/`corectata`/`manuala`,
`campuri_finale`, actorul și data. Acceptarea documentului este blocată cât
timp o extracție existentă încă rulează sau mai poate fi reîncercată, dar nu
depinde de AI dacă nu există un job. RLS oferă rolului web numai SELECT
tenant-scoped; toate mutațiile cozii sunt privilegiate.

**Arhiva lunară materializată**: `arhive_lunare` păstrează versiunea,
starea/lease-ul, prefixurile staging/final, checksum-ul manifestului, numărul și
dimensiunea fișierelor. `fisiere_arhiva_lunara` este manifestul relațional și
leagă fiecare copie de documentul și fișierul-sursă din aceeași firmă/perioadă,
cu checksum sursă = checksum arhivă. Calea finală este
`clients/<firma>/<AAAA-LL>/archive/vNNNN/<primite|emise|fara-directie>/<tip>/`;
artefactele tehnice sunt sub `.system`, iar manifestul CSV final este scris
ultimul ca marcaj de publicare. Numele includ o secvență, metadate lizibile
când există și UUID-ul scurt al fișierului pentru evitarea coliziunilor.

**Flux** (R5 — cu upload intent server-side, D13):
1. UI-ul creează mai întâi obiectul `documente` în stare `draft`, apoi cere
   upload pentru acel document. Serverul inserează un rând în
   `intentii_upload` (RLS: doar pe firmele accesibile, în nume propriu), cu
   `document_id` **obligatoriu** și, la înlocuire,
   `inlocuieste_fisier_id`. FK-ul compus impune ca ținta să aparțină aceluiași
   document încă de la inițiere. Triggerul DB generează/înlocuiește
   `storage_key` (`clients/<firma>/<AAAA-LL>/documents/<intent>`) folosind
   luna perioadei contabile și fixează expirarea la 1h. Obiectele sunt astfel
   separate întâi pe client, apoi pe lună; thumbnail-urile folosesc același
   prefix lunar în subdirectorul `thumbnails`;
   clientul nu poate alege cheia, expirarea sau `folosita_la`. Serverul
   returnează presigned PUT pe exact acea cheie. Limite: **max 25
   MB/fișier, max 300 pagini/PDF**; tipuri: PDF, JPG, PNG, HEIC.
2. **Callback-ul de finalizare primește DOAR id-ul intenției** — niciodată
   `storage_key` sau tenantul de la client. Serverul validează: intenția
   există, aparține utilizatorului curent, nu e expirată, nu e deja
   folosită. Serviciul rulează pe `privileged`, într-o singură tranzacție:
   blochează intenția cu `SELECT ... FOR UPDATE`, verifică obiectul din
   backend-ul local sau R2,
   creează `fisiere_document` cu `upload_intentie_id`, apoi marchează
   `folosita_la`. `app_user` nu are UPDATE pe intenții și nici INSERT/UPDATE
   direct pe fișiere. FK-ul compus garantează aceeași firmă și același
   document, iar `UNIQUE(upload_intentie_id)` împiedică două callback-uri
   concurente să consume aceeași intenție. În implementarea curentă,
   finalizarea apelează imediat procesarea fișierului. Fișierele rămase în
   așteptare sau cu eroare sunt reluate prin
   `python manage.py process_document_files`; procesarea este idempotentă,
   are maximum 3 încercări și un lease de 15 minute pentru fiecare încercare;
   un worker ulterior recuperează automat rândurile rămase `in_lucru` după
   o întrerupere, iar la epuizare setează `eroare` și notifică:
   - verifică existența obiectului și dimensiunea lui;
   - calculează și persistă checksum-ul SHA-256;
   - PDF: validare deschidere, număr pagini, thumbnail prima pagină;
   - imagini: rotație EXIF și thumbnail PNG; originalul rămâne neschimbat.
3. **Curățare**: comanda `python manage.py cleanup_upload_intents` șterge
   obiectele locale/R2 din staging ale intențiilor expirate nefolosite și
   intențiile respective. Programarea periodică aparține mediului de rulare.
4. **Înlocuire** (clarificări): fișier nou cu următoarea versiune disponibilă
   și `inlocuieste_fisier_id`. Noul rând rămâne `activ=false` pe durata
   validării; numai după procesarea reușită, într-o tranzacție, vechiul devine
   `activ=false` și noul `activ=true`. La eroare versiunea veche rămâne activă.
   Două înlocuiri concurente ale aceleiași versiuni nu se suprascriu: prima
   validată câștigă, cealaltă este respinsă. UI-ul afișează versiunea curentă
   și istoricul complet, ordonate pe `ordine`, apoi `versiune`.
5. **Export ZIP** (tabela `exporturi`): solicitarea creează un job persistent
   în PostgreSQL. Comanda `python manage.py process_exports` îl execută o dată,
   iar `--watch` interoghează continuu coada; blocările advisory împiedică
   procesarea concurentă. Arhiva este deterministă, organizată în
   `categorie/tip-document/`, conține `manifest.csv`, reverifică checksum-ul
   surselor, expiră după 7 zile și notifică solicitantul la finalizare.
   `python manage.py cleanup_expired_exports` șterge exporturile expirate.
6. **Închiderea/arhiva lunară**: solicitarea contabilului trece perioada în
   `inchidere_in_curs` în tranzacția web, apoi programează jobul numai după
   commit pentru a evita blocarea încrucișată între conexiunea RLS și worker.
   Workerul copiază în staging, verifică SHA-256, publică copiile finale și
   scrie manifestul ultimul. Într-o tranzacție privilegiată marchează
   documentele `arhivat`, arhiva `finalizata` și perioada `inchisa`; o versiune
   anterioară devine `inlocuita`, fără ștergere. Lease-ul recuperează joburile
   întrerupte; după trei eșecuri perioada revine în `in_lucru` cu istoric și
   audit. `process_document_analyses --watch` procesează această coadă chiar
   dacă AI este dezactivat.
7. Scanare malware: în MVP — validare strictă de tip + deschiderea efectivă
   a fișierelor în pipeline (corupte → `eroare`); ClamAV = faza 2. În
   producție fișierele nu se servesc niciodată direct din domeniul
   aplicației: accesul se face prin presigned GET R2 cu expirare scurtă și
   dispoziție controlată (`inline`/`attachment`). Endpoint-ul semnat local
   este exclusiv pentru dezvoltare.

---

## 10. Notificări (destinatari expliciți)

| Eveniment | Destinatari | Canal |
|---|---|---|
| document sau serie nouă `trimis(ă)` | contabilul responsabil al perioadei (fallback: contabilii alocați firmei); o singură notificare per serie | in-app |
| clarificări cerute | autorul documentului + client_admin-ii firmei | in-app + email |
| perioadă confirmată de client | contabilul responsabil | in-app + email |
| toate clarificările rezolvate | contabilul responsabil | in-app |
| eroare de procesare fișier (după epuizarea retry-urilor) | autorul upload-ului + contabilul responsabil | in-app |
| perioadă închisă | client_admin-ii firmei | in-app + email |
| reminder termen (T-3 zile și T, dacă există cerințe `lipsa`) | client_admin-ii + operatorii firmei | email |
| export finalizat | solicitantul | in-app |
| invitație | emailul invitat | email |
| comentariu nou | participanții la fir + contabilul responsabil | in-app |

Notificările sunt create de serviciul privilegiat numai după commit-ul
tranzacției de business. Fiecare livrare are o `cheie_deduplicare` SHA-256
unică, derivată din eveniment + destinatar; reluarea aceluiași callback nu
creează alt rând și nu retrimite emailul. Pe conexiunea web `app_user` nu are
INSERT și poate actualiza exclusiv coloana `citita` a propriilor rânduri prin
RLS. În dezvoltarea locală emailurile folosesc backend-ul console Django;
producția configurează backend-ul SMTP/API prin variabile de mediu.

---

## 10A. Predări fizice

Predările sunt legate de o firmă și, în fluxul MVP, de perioada contabilă
din care au fost inițiate. `client_admin`, `client_operator`, `contabil` și
`contabil_coordonator` pot programa o predare cât timp perioada nu este
închisă. Numai `contabil`/`contabil_coordonator` pot avansa fluxul fizic:
`programata → preluata → receptionata → returnata`. La preluare se fixează
contabilul responsabil și data; următoarele tranziții fixează exclusiv data
corespunzătoare și nu pot sări stări.

Metodele fizice (`curier`, `posta`, `ridicare_contabil`, `predare_client`)
cer persoana care predă, cel puțin o cutie și o dată programată. Metoda
`exclusiv_digital` se înregistrează direct ca `receptionata`, cu zero cutii,
fără date de transport și fără tranziții fizice. Constrângerile bazei verifică
această coerență și ordinea datelor efective.

Pe conexiunea web tabela este numai pentru citire sub RLS. Crearea și toate
tranzițiile rulează pe conexiunea privilegiată numai după reverificarea
rolului și a apartenenței utilizatorului la firma de contabilitate/firma clientă și emit evenimente
în `audit_log`.

După `receptionata`, digitizarea este **opțională** și are o stare separată de
logistica originalelor: `nedecisa`, `nu_este_necesara`, `in_lucru`,
`finalizata`. Contabilul alege explicit dacă pornește digitizarea și poate
declara un număr estimat, modificabil. Documentele create în acest context au
`predare_documente_id`; FK-ul compus garantează aceeași firmă și aceeași
perioadă. Progresul este derivat din documentele legate pentru care **toate**
fișierele active sunt procesate, nu dintr-un contor editabil. Finalizarea cere
cel puțin un document, toate documentele și fișierele active legate procesate
și, dacă există estimare, atingerea ei. Fluxul poate fi redeschis auditat
pentru completări cât timp dosarul lunar este editabil. O digitizare `in_lucru`
blochează închiderea dosarului. Alegerea „nu este necesară” păstrează exclusiv
trasabilitatea fizică și poate fi schimbată ulterior în „în lucru”.

---

## 11. Cerințe nefuncționale (MVP)

- **Volume asumate**: zeci de firme cliente per firmă de contabilitate,
  sute–mii de documente/lună/firmă,
  fișiere de ordinul MB. Read-heavy. Fără replicas/materialized views/partiții
  în MVP; candidat viitor: partiționarea `audit_log` (lunar, `creat_la`).
- **Retenție**: regula generală din Legea contabilității 82/1991 (art. 25):
  documentele justificative, registrele contabile și situațiile financiare
  — inclusiv statele de salarii — se păstrează **5 ani, de la 1 iulie a
  anului următor** exercițiului. *Dosarele de personal* (alt regim) nu fac
  obiectul platformei. Implementare pe două niveluri: (1)
  `tipuri_document.retentie_ani` (NULL sau minimum 5; NULL = implicitul legal)
  și (2) `documente.retentie_extinsa_pana_la` — pentru documentele care
  atestă proveniența bunurilor cu durată de viață mai mare decât termenul
  general, unde retenția depinde de DOCUMENT, nu de tip; o setează
  contabilul și poate doar extinde termenul. Data cea mai devreme de
  purjare este calculată de fiecare dată ca `GREATEST(termenul legal de 5
  ani, termenul tipului, retentie_extinsa_pana_la)`; o dată de extensie mai
  mică decât termenul legal este respinsă de trigger și nu îl poate
  înlocui. Matricea se validează juridic înainte de lansare. „Nicio ștergere
  fizică" = nimic nu se șterge ÎN perioada de retenție. Comanda de purjare
  ulterioară, privilegiată și auditată, nu este încă implementată.
- **Țintă de producție — Backup/DR (neimplementată în repository)**:
  backup zilnic + PITR (WAL); RPO ≤ 24h (țintă 15 min cu
  PITR), RTO ≤ 4h; test de restore trimestrial; R2 cu versionare de obiecte.
- **Securitate infrastructură**: repository-ul include setări separate de
  producție, cookie-uri `Secure`/`HttpOnly`, redirect HTTPS, HSTS configurabil,
  `X-Frame-Options: DENY` și limitare de autentificare partajată prin cache-ul
  PostgreSQL. În infrastructură rămân obligatorii TLS, criptarea at-rest și
  secret manager-ul.
- **Țintă operațională — GDPR**: datele în UE; platforma = împuternicit al
  firmei de contabilitate; export
  și anonimizare utilizator la cerere (anonimizare = înlocuirea datelor
  personale în `utilizatori`, NU ștergerea rândului — FK-urile de audit
  rămân valide); DPA cu providerii.
- **Monitorizare pentru producție (neimplementată încă în repository)**:
  activare `pg_stat_statements`, colectare centralizată de erori și alerte
  pentru joburi rămase în așteptare sau eșuate.

---

## 12. Structura proiectului

```
config/                  # settings dev/test/migration/prod/admin, urls, exemple launchd
core/                    # bootstrap, middleware RLS, readiness, audit, operații periodice
conturi/                 # AUTH_USER_MODEL, autentificare, invitatii, utilizator_firma
firme/                   # firme, parteneri, conturi_financiare, configurare
perioade/                # perioade, cerinte, confirmare/închidere/redeschidere
documente/               # documente, fisiere, comentarii, istoric, upload, verificare
logistica/               # predari_documente
notificari/              # in-app + email, remindere prin scheduler/command
exporturi/               # export ZIP
templates/               # interfața server-rendered
specsv5/roles.sql        # rolurile de cluster (provisioning, NU migrare)
specsv5/schema_starter.sql # schema SQL de referință
specsv5/seed_test.sql    # datele suitei SQL
specsv5/test_rls.sh      # suita PostgreSQL/RLS auto-suficientă
```

## 13. Ecranele MVP

Client: dosarul lunar (checklist cu statusuri, număr de documente/fișiere,
serii repetabile per rând și buton „Am transmis toate documentele” activ doar
cu cerințele în `primit`/`nu_se_aplica`), upload multi-fișier cu alegere
explicită între documente separate și pagini ale aceluiași document, progres
și recuperare individuală la eroare; detaliu document (versiuni, comentarii,
reîncărcare).

Contabil: dashboard portofoliu (carduri agregate + tabel firme cu status
perioadă), dosar lunar cu coadă de verificare (preview PDF + acceptă/
clarificări/procesat + formular metadate la acceptare), închidere perioadă,
export ZIP, predări fizice, administrare parteneri.

Admin al firmei de contabilitate: ecrane proprii pe conexiunea NORMALĂ (protejate de RLS),
care apelează serviciile privilegiate doar pentru scrierile administrative
(§2). Django Admin privilegiat: EXCLUSIV superuserul platformei.

## 14. Testare — minim obligatoriu

Baseline-ul curent conține două niveluri complementare de testare:

- **124 verificări PostgreSQL/RLS** în `specsv5/test_rls.sh`, pe topologia
  cu `migrare` owner non-superuser, `web_app` protejat de RLS și `worker`
  privilegiat. Suita reconstruiește baza de test și verifică provisioningul,
  granturile, izolarea tenanturilor, constrângerile și tabelele adăugate
  pentru notificări, exporturi, predări, inbox, analiza AI, pagini OCR,
  derivări, extrageri structurate și arhive lunare;
- **137 teste Django/pytest** pentru autorizare și servicii, limitarea
  autentificării, schimbarea/resetarea parolei, health/readiness, setările de producție, operațiile
  periodice, rollback-ul și protecția streaming din middleware-ul RLS,
  autentificare/rutare DB,
  perioade, documente, upload și procesare, normalizarea extragerilor,
  manifestul/arhiva lunară, notificări/remindere, exporturi și logistică.

Aceste numere descriu testele existente după integrarea Phases 4–5 din 19 iulie 2026;
orice test adăugat ulterior trebuie reflectat aici. Auditul de release trebuie
să verifice în continuare matricea completă rol × operație și scenariile de
eșec/concurență înaintea lansării în producție.

## 15. Ce NU facem în MVP

Integrare SAGA; separare sau contabilizare automată fără revizuire umană;
permisiuni granulare (tabele
roluri/permisiuni); cutii cu QR; e-Factura/ANAF; aplicație mobilă nativă;
rapoarte avansate; ClamAV.

## 16. Stadiul implementării

Sunt implementate: fundația Django/PostgreSQL și RLS, autentificarea cu
limitare partajată și
admin-ul separat, utilizatorii/invitațiile/alocările, firmele cliente și
configurarea checklist-ului, perioadele și tranzițiile lor, documentele și
comentariile, upload-ul local/R2 cu procesare și versiuni, dashboard-ul și
coada de verificare, inboxul multiplu, citirea OCR locală, preview-urile,
separarea confirmată de contabil și clasificarea manuală/AI asistată cu
revizuire umană, extracția structurată cu confirmare/corectare umană, arhiva
lunară versionată cu manifest și checksum, notificările/emailurile/reminderele,
exportul ZIP și predările de documente, setările de producție,
health/readiness, verificarea automată de release și joburile periodice fără
Docker.

Nu fac parte din implementarea curentă: Docker, Redis, Celery, deschiderea
automată lunară a perioadelor, contabilizarea/postarea automată în SAGA,
ClamAV și observabilitatea de producție.
Înainte de lansare rămân porțile externe din `docs/RELEASE_READINESS.md`:
configurarea providerilor și domeniilor reale, testul backup/restore,
monitorizarea operațională și validarea juridică a matricei de retenție.
