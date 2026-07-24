# Italtecnica WiNet — HTTP API (10.6.2.100)

WiFi modul **Net Software srl "WiNet"**, fw `0.17`, server `NetSoftware-httpd/0.4`.
Sedí na sériové lince inverteru Italtecnica (Sirio) u čerpadla Wilo a vystavuje ho přes HTTP.

Jen port **80**. Žádný Modbus TCP (502 zavřený), žádné MQTT, žádné HTTPS.
Odpovědi jsou `Content-Encoding: gzip` i bez `Accept-Encoding` → klient musí umět gzip
(`curl --compressed`, `requests` to řeší samo).

Webové UI polluje `key=001` po **200 ms**; pro integraci stačí 1–5 s.

### Latence — změřeno na živém modulu

| volání | medián | poznámka |
|---|---|---|
| `key=001` runtime snapshot | **15 ms** | 0 chyb ze 40 |
| `/ajax/get-status` | 42 ms | |
| `key=002` čtení parametru | **0,7–1,9 s** | občas timeout / reset spojení |
| `key=007`/`008` krok parametru | **~1,56 s** | velmi konzistentní |

Rozdíl je zásadní pro návrh integrace. Runtime snapshot je hotový snímek displeje,
který modul drží v paměti. Čtení parametru ho nutí dojít si pro hodnotu do invertoru
po sériové lince — je 50× pomalejší a nespolehlivé. **Parametry netahat v každém
pollu**; cachovat je, obnovovat řádově po minutách a po zápisu je aktualizovat
z odpovědi (ta výslednou hodnotu nese).

Souběžné requesty modul zvládne, ale keep-alive spojení recykluje po svém —
aiohttp pak dostane `ServerDisconnectedError` nebo `Connection reset by peer`
na socketu z poolu. Čtení je bezpečné jednou zopakovat, **zápis nikdy**.

## Endpointy

| Endpoint | Metoda | Data | Popis |
|---|---|---|---|
| `/ajax/get-registers` | POST | `key`, `index` | čtení dat inverteru |
| `/ajax/set-registers` | POST | `key`, `index` | zápis / povely |
| `/ajax/login` | GET | — | stav přihlášení `{"logged":bool}` |
| `/ajax/login` | POST | `pin` | přihlášení (PIN, max 8 znaků) |
| `/ajax/logout` | POST | — | odhlášení |
| `/ajax/get-status` | GET | — | stav WiFi/IP/čas/fw |
| `/ajax/get-dhcp` | GET | — | DHCP / statická IP |
| `/ajax/get-networks` | GET | — | sken WiFi sítí |
| `/ajax/connect` | POST | — | připojení k WiFi |
| `/ajax/get-gpio` | GET | — | GPIO (vrací prázdno) |
| `/ajax/reboot` | POST | — | restart modulu |
| `/ajax/upgrade`, `/ajax/check-upg-sts` | POST | — | FW upgrade |

### Klíče (`key`)

Posílají se jako **třímístný string s nulami**: `"001"`, ne `1`. V odpovědi se vrací jako int.

| key | směr | data | význam |
|---|---|---|---|
| `001` | get | — | runtime snapshot (viz níže) |
| `002` | get | `index` | čtení uživatelského parametru |
| `003` | get | `index` | čtení pokročilého parametru — **vyžaduje login**, jinak `{}` |
| `007` / `008` | set | `index` | inkrement / dekrement uživatelského parametru |
| `009` / `010` | set | `index` | inkrement / dekrement pokročilého parametru |
| `011` | set | — | **toggle RUN/STAND-BY** (start/stop čerpadla) |

## `key=001` — runtime data

```json
{"key":1,"standBy":0,"flagError":0,"master":1,"barOrPsi":0,"doubleSetPoint":0,
 "extEnabled":1,"extErr":0,"motorOn":0,"noException":0,"backLightState":0,
 "pilota":0,"pumpMan":0,"temp":36,"tempIgbt":19,"amp":0,"ampMax":85,"volt":236,
 "freq":0,"freqMax":50,"press":34,"setPointPress":35,
 "errorActive":false,"errorNumber":0,
 "e0":0,"e1":0,"e2":20,"e3":13,"e4":0,"e5":0,"e6":23,"e7":0,"e8":0,"e9":1,
 "e10":0,"e11":0,"e12":0,"e13":0,
 "hPowerOn":28117,"hPowerRunning":1030,"nrStarts":13934}
```

### Škálování

| pole | výpočet | jednotka |
|---|---|---|
| `press`, `setPointPress` | `/10` (jen když `barOrPsi==0`; u PSI `/1`) | bar / psi |
| `amp`, `ampMax` | `/10` | A |
| `volt` | ×1 | V |
| `freq`, `freqMax` | ×1 | Hz |
| `temp`, `tempIgbt` | ×1 | °C |
| `hPowerOn`, `hPowerRunning` | ×1 | h |
| `nrStarts` | ×1 | počet startů |

### Stavy a příznaky

- **Stav** (priorita): `flagError==1` → `ERROR`; jinak `standBy==1` → `STAND-BY`; jinak `ON`.
- `motorOn` — motor běží
- `master` — master v kaskádě
- `doubleSetPoint` — aktivní 2. set-point
- `extEnabled` / `extErr` — externí povolení / externí chyba
- `pilota` — pilotní čerpadlo
- `pumpMan` — ruční režim
- `barOrPsi` — 0 = bar, 1 = psi
- `errorActive` + `errorNumber` — aktuální chyba (platí jen při `flagError==1`)
- `e0`…`e13` — **čítače historie** jednotlivých chyb (kolikrát nastaly)

### Chybové kódy (`errorNumber` / index `eN`)

| # | chyba | popis |
|---|---|---|
| 0 | E0 Low voltage | napájecí napětí příliš nízké |
| 1 | E1 High voltage | napájecí napětí příliš vysoké |
| 2 | E2 Short circuit | zkrat na výstupu invertoru |
| 3 | E3 Dry running | běh nasucho / nedostatek vody v sání |
| 4 | E4 Ambient temperature | překročena max. vnitřní teplota invertoru |
| 5 | E5 Module temperature | překročena max. teplota IGBT modulu |
| 6 | E6 Overload | odběr čerpadla přesáhl Imax |
| 7 | E7 Out of curve | průtok mimo jmenovitou křivku |
| 8 | E8 Serial error | chyba interní sériové komunikace (Sirio) |
| 9 | E9 Pressure limit | překročena mezní tlaková hranice |
| 10 | E10 External error | externí chyba z I/O desky (vstup sepnut) |
| 11 | E11 Max starts/hour | překročen max. počet startů za hodinu |
| 12 | E12 Error 12V | anomálie vnitřního nízkonapěťového napájení |
| 13 | E13 Pressure sensor error | chyba tlakového čidla |

## Parametry

`POST /ajax/get-registers` s `key=002&index=<n>` →
`{"key":2,"result":true,"parIndex":0,"value":35}`

`value` je **surová hodnota**, převod je per-parametr (viz sloupec „převod“).

### Uživatelské parametry (`key=002` čtení, `007`/`008` +/−)

| idx | UI | název | převod / kódování |
|---|---|---|---|
| 0 | 0.0 | Pmax (set-point) | `/10` bar |
| 1 | 0.1 | Delta tlaku pro start | `/10` bar |
| 2 | 0.2 | Tlak pro běh nasucho | `/10` bar |
| 3 | 0.3 | Mezní tlak (ochrana přetlaku) | `/10` bar |
| 4 | 0.4 | Pmax 2 (set-point 2) | `/10` bar |
| 5 | 0.5 | Delta tlaku pro stop | `/10` bar |
| 6 | 0.6 | Jednotka | 9=BAR, 10=PSI |
| 10 | 1.0 | Imax | `/10` A |
| 11 | 1.1 | Směr otáčení | 21=`-->`, 22=`<--` |
| 12 | 1.2 | Minimální frekvence | Hz |
| 13 | 1.3 | Frekvence stopu | Hz |
| 14 | 1.4 | Jmenovitá frekvence motoru | Hz |
| 15 | 1.5 | Spínací frekvence | kHz |
| 16 | 1.6 | Korekce frekvence | `value-10` Hz |
| 17 | 1.7 | Soft-start | 7=ON, 8=OFF |
| 20 | 2.0 | Aktivace průtokoměru | 7=ON, 8=OFF |
| 21 | 2.1 | Zdroj povelu | 18=MAN, 19=0-10V, 20=PRESS |
| 22 | 2.2 | Funkce pomocného kontaktu | 23=`1<->`, 24=`2<--`, 25=`3 X2` |
| 23 | 2.3 | Funkce vstupu I/O desky | 24=`2<--`, 25=`3 X2`, 26=ERR, 27=OFF |
| 24 | 2.4 | Funkce výstupu I/O desky | 3=OFF, 4=ERR, 5=P.ON, 6=AUX |
| 25 | 2.5 | Zpoždění stopu | `/10` s |
| 26 | 2.6 | Interval autoresetu | min |
| 27 | 2.7 | Počet pokusů autoresetu | — |
| 28 | 2.8 | Celkový automatický reset | 7=ON, 8=OFF |

### Pokročilé parametry (`key=003` čtení, `009`/`010` +/−) — jen po přihlášení

| idx | UI | název | převod |
|---|---|---|---|
| 40 | 4.0 | Vboost | % |
| 41 | 4.1 | Zpoždění běhu nasucho | s |
| 42 | 4.2 | Ochrana startů/hod | 11=OFF, 12–17 → `(v-11)*10` |
| 43 | 4.3 | Antiblokovací ochrana | 7=ON, 8=OFF |
| 44 | 4.4 | Dead time PWM | `v` ×125 ns |
| 45 | 4.5 | Ki | — |
| 46 | 4.6 | Kp | — |
| 47 | 4.7 | Doba boostu | `*10` ms |
| 48 | 4.8 | Režim relé I/O | 1=N.O., 2=N.C. |
| 50 | 5.0 | Ta max | — |
| 51 | 5.1 | Tm max | — |
| 52 | 5.2 | Index redukce Ta | — |
| 53 | 5.3 | Index redukce Tm | — |
| 54 | 5.4 | Minimální průtok | — |
| 55 | 5.5 | IPM mod. | — |
| 56 | 5.6 | Minimální napětí | — |
| 57 | 5.7 | Maximální napětí | — |
| 59 | 5.9 | Debug proměnná | — |

## Zápis — důležité omezení

**Neexistuje endpoint pro nastavení hodnoty.** Jde jen inkrementovat / dekrementovat
o jeden krok (`key=007`–`010`), přesně jak fungují tlačítka `+`/`−` v UI.
Nastavení set-pointu z 3.5 na 4.0 bar tedy znamená 5× zavolat `007` s `index=0`.

### Ověřeno na živém zařízení

`key=007` / `008` **vrací výslednou hodnotu po kroku** — smyčka je tedy uzavřená
a nemusí se slepě opakovat:

```
POST /ajax/set-registers  key=007&index=0  -> {"key":3,"result":true,"parIndex":0,"value":37}
POST /ajax/set-registers  key=008&index=0  -> {"key":2,"result":true,"parIndex":0,"value":36}
```

⚠️ Pole `key` v odpovědi **neodpovídá poslanému klíči** (na `007` přišlo `3`, na `008` přišlo `2`).
Nespoléhat na něj při párování odpovědí. Směrodatné jsou `parIndex` a `value`.

`key=011` přepíná RUN ⇄ STAND-BY. Je to **toggle**, ne absolutní příkaz, a odpověď
**nenese výsledný stav** — jen potvrzení:

```
POST /ajax/set-registers  key=011  -> {"key":11,"result":true}
```

Ověřeno: `standBy` 0 → 1 → 0. Stav se musí dočíst z `key=001`; mezi přepnutím
a čtením nechat ~0.5–1 s.

### Doporučený postup zápisu

Konvergenční smyčka, nikdy slepý retry (inkrement není idempotentní — retry po
timeoutu by přičetl dvakrát):

```
dokud actual != target a zbývají pokusy:
    actual = odpověď(007|008).value
    když se actual po kroku nezměnil: konec — naraženo na limit
```

Zápisy serializovat (jeden request v letu, jako fronta ve webovém UI).
Pozor na EEPROM: každý krok je pravděpodobně zápis do paměti invertoru —
nestavět na tom průběžnou regulaci.

**Krok trvá ~1,56 s**, takže limitem není počet kroků, ale čas: změna set-pointu
o 1 bar ≈ 16 s, plný přejezd 0.5–10 bar přes dvě minuty. Konvergenci proto omezit
i časovým rozpočtem. Zastavení v půlce je bezpečné — parametr zůstane na platné
mezihodnotě a další volání dojede zbytek, protože smyčka si nejdřív přečte
skutečný stav.

### Konfigurace tohoto invertoru (naměřeno)

| parametr | hodnota |
|---|---|
| 0.0 Pmax (set-point) | 3.6 bar |
| 0.1 delta pro start | 1.0 bar |
| 0.2 tlak běhu nasucho | 0.5 bar |
| 0.3 tlaková mez (ochrana přetlaku) | 10.0 bar |
| 0.4 Pmax 2 | 1.5 bar |
| 0.5 delta pro stop | 2.5 bar |
| 0.6 jednotka | 9 = BAR |
| 1.0 Imax | 8.5 A |

## Přihlášení

```
GET  /ajax/login            → {"logged":false}
POST /ajax/login  pin=xxxx  → {"logged":true|false}
POST /ajax/logout
```

PIN max 8 znaků (číselný, `<input type="password">`). Bez přihlášení jsou čtení
runtime dat i uživatelských parametrů dostupná **anonymně** — login je potřeba
jen pro pokročilé parametry (`key=003`, `009`, `010`).

Poznámka k bezpečnosti: **ověřeno, že bez jakékoli autentizace fungují i zápisy** —
`key=011` (start/stop čerpadla) i `key=007`/`008` (změna set-pointu). Kdokoli se
sítí na modul může čerpadlo zastavit nebo přenastavit. Modul patří do izolované IoT VLAN.

Nedokumentované `key` hodnoty na `get-registers` vrací `{}` bez pozorovaného
vedlejšího efektu (testováno `000`, `004`–`006`, `012`, `013`, `020`, `099`, `100`).

## Stav modulu (`/ajax/get-status`)

```json
{"status":5,"apConnected":0,"lastDisconnectReason":202,"lastCloudError":0,
 "currentApIp":"192.168.10.1","currentIp":"10.6.2.100","currentMask":"255.255.255.0",
 "currentGw":"10.6.2.1","inetTime":"2026-07-24 22:36","inetWeekDay":5,"client":2,
 "network":"Richterovi - IOT","signal":3,"rssi":-63,"fwVer":"0.17","boot":1}
```

Užitečné pro diagnostiku: `rssi`, `signal` (0–4), `fwVer`, `inetTime`.

## Stránky UI

`index.html` → redirect na `management.html` (hlavní, `management.js`),
dále `user.html` (login/PIN), `status.html` (WiFi), `networks.html`, `dhcp.html`.
