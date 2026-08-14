# nfc-ordering-system

Izlog jednog privatnog sustava: gost prisloni telefon na predmet na stolu,
naruci, i narudzba stigne konobaru s tocnim brojem stola. Tri sucelja (gost,
ploca konobara, uprava), **bez ijedne vanjske ovisnosti** osim standardne
biblioteke Pythona.

Ovdje nije cijeli projekt. Ovdje je opis kako je gradjen, sest odluka koje su
ga oblikovale, i **jedan cijeli modul s testovima** da se vidi kako izgleda
stvarni kod, a ne samo tvrdnja o njemu.

---

## Izmjereno, ne prepisano

Brojke ispod izmjerene su pokretanjem nad izvornim repozitorijem
14. 8. 2026., na Windowsu 11, Python 3.13.1:

| Mjera | Vrijednost |
|---|---|
| Redaka Pythona u jezgri | 48 963 |
| Modula (bez testova) | 45 |
| Testnih datoteka / metoda | 49 / 1315 |
| Prikupljeno i pokrenuto na Windowsu | 1243 testa u 208 s |
| Prolazi na Windowsu | 1167 |
| Pada na Windowsu | 75 |
| Vanjskih ovisnosti | 0 |

**O tih 75 padova, posteno.** Sustav je pisan i dokazan na macOS-u; Windows
mu nije ciljna platforma. Padovi nisu ravnomjerno rasprseni: 41 je u jednom
jedinom modulu (rad s vise lokala nad istom bazom), a ostalo su testovi koji
citaju `/proc`, koriste `lsof` ili traze POSIX prava. Prvi je stvarna
regresija koju treba popraviti; drugi su ocekivani. Tvrdnja "sve prolazi"
ovdje ne stoji i nije napisana.

---

## Sest odluka

### 1. Cekanje na mrezi ide u paralelu, rad nad bazom ne

Posluzitelj je najprije bio jednonitan i svako cekanje na mrezi se zbrajalo:
pet veza koje posalju nedovrseno zaglavlje i sute drzale su normalnog gosta
24,5 sekunde, pedeset njih preko cetiri minute. Uzrok nije bila baza nego to
sto je jedna nit cekala na uticnici.

Razdvojene su dvije stvari koje su dotad bile jedna. Rukovanje TLS-om,
citanje zaglavlja i ispis odgovora idu u vise dretvi, jer traju onoliko koliko
traje tudji telefon. Rad nad bazom ostaje serijaliziran, jedan po jedan.

Zasto se rad nad bazom ne pusta u paralelu, iako bi WAL to podnio: javni broj
narudzbe racuna se kao `MAX + 1`, provjera kljuca idempotencije prethodi
upisu, stanje stavke se cita pa mijenja. Takvih mjesta su desetci i nisu
oznacena. Pustiti ih u paralelu znaci prevesti kvar s mreze u kvar u
podacima, a podaci su jedino sto se ne da popraviti ponovnim pokretanjem.

Cijena je izgovorena do kraja: dok jedan zahtjev radi nad bazom, ostali
cekaju. Isplati se dok je rad nad bazom kratak, a mjeri se u desetinkama
milisekunde.

### 2. Brava koja zna izaci iz reda

Jedino mjesto koje unutar obrade ceka na necem sporom je dohvat javnih kljuceva
vanjskog davatelja prijave. Za njega postoji `predah()`: potpuni izlazak iz
reda dok se ceka mreza, i povratak na istu dubinu gnijezdenja.

```python
@contextmanager
def predah(self):
    if self._vlasnik != threading.get_ident():
        yield                      # dretva koja bravu ne drzi: bez ucinka
        return
    dubina = self._dubina
    self._vlasnik = None
    self._dubina = 0
    self._brava.release()
    try:
        yield
    finally:
        self._brava.acquire()
        self._vlasnik = threading.get_ident()
        self._dubina = dubina      # vraca se tocno ista dubina
```

`threading.RLock` to zna kroz `_release_save`, ali te metode postoje radi
`Condition` i nisu obecane kao sucelje. Dvadesetak redaka vlastitog brojaca
dubine jeftinije je od oslanjanja na tudji dogovor s podvlakom.

Cijeli modul je ovdje: [`primjer/brava.py`](primjer/brava.py), 117 redaka, uz
[10 testova](testovi/test_brava.py) pisanih za ovaj izlog.

### 3. Verzija sheme zivi u samoj datoteci baze

```python
verzija = int(v.execute("PRAGMA user_version").fetchone()[0])
...
v.execute("PRAGMA user_version = %d" % migracija.broj)
```

Ne tablicom, iako je tablica citljivija. Tri razloga:

- Broj je dio datoteke, pa putuje s njom. Kopija, vracena pricuva i datoteka
  prenesena na drugo racunalo nose svoju verziju sa sobom; tablica koju netko
  zaboravi prepisati laze o tome sto u bazi stoji.
- Upisuje se unutar transakcije i s njom se povlaci natrag. Provjereno, ne
  pretpostavljeno: `BEGIN`, `PRAGMA user_version = 7`, `ROLLBACK` ostavlja
  staru vrijednost. Zato se "migracija je izvedena" i "broj je podignut" ne
  mogu raziciti, a to je jedini nacin da se migracija ne izvede dvaput.
- Cuva ga i `sqlite3.Connection.backup`.

Tablica migracija ipak postoji, ali kao dnevnik za covjeka koji trazi kvar,
ne kao izvor istine.

Pricuva prije migracije je obavezna. Transakcija cuva od prekida, ali ne cuva
od migracije koja se uredno potvrdi i pogrijesi. Padne li bilo sto, sustav
prvo pogleda je li baza vec u zatecenom stanju (transakcija cesto obavi posao
sama); ako nije, vrati punu pricuvu i **provjeri da je vracena datoteka doista
jednaka zatecenoj**, ista verzija i isti otisak sadrzaja. Tek tada javlja
gresku.

Zasto uopce: naljepnice na stolovima su zalijepljene i na njima stoji
identifikator stola. Obrisana baza znaci nove identifikatore, dakle sve
naljepnice u smecu.

### 4. Datoteka koja se procita i na krivom Pythonu

Svaka datoteka sustava pocinje s `from __future__ import annotations`. Tu
naredbu stari Python ne poznaje, pa takva datoteka pukne jos pri citanju,
prije nego ijedan njezin redak dobije priliku javiti sto fali. Ishod na tudjem
racunalu je sintaksna greska iz sredine datoteke koju vlasnik nikad nije
otvorio.

Dvije datoteke zato su pisane starom sintaksom, bez f-nizova i bez napomena o
tipovima: ona koja zna inacicu i ona koja provjerava okolinu. One se procitaju
i na Pythonu 2.7 i kazu jednu razumljivu recenicu.

```python
NAJMANJI_PYTHON = (3, 9)        # ispod se ne pokrece
ISPROBAN_PYTHON = (3, 9, 6)     # jedina inacica na kojoj je cijeli skup testova prosao
NAJVISI_ISPROBAN_PYTHON = (3, 9)  # iznad: upozorenje, ne odbijanje
```

Neisprobano nije isto sto i "vjerojatno radi", pa se ispod granice odbija. Ali
odbiti noviji Python znacilo bi da se sustav ne da isporuciti na racunalo
kupljeno ove godine, pa se iznad granice pusta uz izricitu napomenu da to
nitko nije vidio.

### 5. Isporuka kao jedna arhiva s popisom otisaka

Sustav se pakira u jednu arhivu od oko 800 kB sa `SHA-256` popisom svih
datoteka i branom protiv putanja s ovog racunala. Prije pokretanja na tudjem
racunalu jedna naredba provjerava Python, cjelovitost isporuke, prava, disk,
vrata i sat.

Predpolijetna provjera pisana je starom sintaksom iz razloga iz tocke 4: poruka
o prestarom tumacu ne smije i sama biti sintaksna greska.

### 6. Prva brojka inacice ostaje nula

```python
INACICA = "0.9.0"
```

Ostaje nula dok sustav ne odradi jedan cijeli radni dan u stvarnom lokalu.
Sve dosad izmjereno izmjereno je na razvojnom racunalu, a to nije isto.

---

## Sto ovaj sustav jos nije

Ovo stoji ovdje jer izlog bez toga nije istinit:

- **Nula lokala i nula gostiju.** Sav promet dosad je s razvojnog racunala.
- **Linux nikad nije pokrenut**, a Linux je ciljna platforma. Jedinice usluge
  i skripta postave napisane su, ali nikad izvedene.
- **Dugotrajan rad dokazan je na 40 minuta**, ne na dvanaestosatnu smjenu.
- **Put od koda do fizicke oznake nikad nije prosao do kraja**: alat koji pise
  zapis na oznaku nije pokrenut na stvarnom uredjaju.
- **Citanje kroz stijenku nije izmjereno.** Vrijednost domete dolazi iz
  deklaracije proizvodjaca, ne iz mjerenja.

Tehnicka strana je najdalje dosla; sve sto nedostaje je izvan koda.

---

## Pokretanje ovog repozitorija

```
python -m pytest testovi -q
```

Testira se `primjer/brava.py`, jedini modul koji je ovdje u cijelosti.
Potreban je samo `pytest`; sam modul ne trazi nista izvan standardne
biblioteke.

---

## Licenca

Apache-2.0, vidi [LICENSE](LICENSE). Odnosi se na kod i tekst u ovom
repozitoriju. Puni sustav nije objavljen.
