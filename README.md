# nfc-ordering-system

Gost prisloni telefon na predmet na stolu, naruci, i narudzba stigne konobaru s
tocnim brojem stola. Tri sucelja, gost, ploca konobara i uprava, napisana bez
ijedne vanjske ovisnosti osim standardne biblioteke Pythona.

Ovo nije cijeli sustav nego izlog. Ispod je opis kako je gradjen i zasto je
gradjen tako, uz jedan modul objavljen u cijelosti da se vidi kako izgleda
stvarni kod, a ne samo tvrdnja o njemu.

## Brojke, i sto s njima nije u redu

Izmjereno pokretanjem 14. 8. 2026. na Windowsu 11, Python 3.13.1. Jezgra ima
48 963 retka u 45 modula, uz 49 testnih datoteka i 1315 testnih metoda. Od
prikupljenih 1243 testa, u 208 sekundi, prolazi 1167, a pada 75.

Tih 75 padova ne treba zaobici. Sustav je pisan i dokazan na macOS-u i Windows
mu nije ciljna platforma, ali padovi nisu ravnomjerno rasprseni: 41 je u jednom
jedinom modulu koji vodi vise lokala nad istom bazom, a ostalo su testovi koji
citaju `/proc`, koriste `lsof` ili traze POSIX prava. Prvi je stvarna
regresija koju treba popraviti, drugi su ocekivani. Tvrdnja "sve prolazi" ovdje
ne stoji i nije napisana.

Sto se moze provjeriti odmah, bez pristupa zatvorenom repozitoriju:

```bash
git clone https://github.com/hm53-byte/nfc-ordering-system && cd nfc-ordering-system
pip install pytest && python -m pytest testovi -q
```

To pokrece deset testova nad objavljenim modulom. Brojke iz prethodnog odlomka
time se ne provjeravaju; one su iz zatvorenog repozitorija i navedene su s
datumom, platformom i inacicom tumaca da se zna sto je tvrdnja a sto dokaz.

## Cekanje na mrezi i rad nad bazom nisu ista stvar

Posluzitelj je najprije bio jednonitan, pa se svako cekanje zbrajalo. Pet veza
koje posalju nedovrseno zaglavlje i sute drzale su normalnog gosta 24,5
sekunde, a pedeset njih preko cetiri minute. Uzrok nije bila baza nego to sto je
jedna nit cekala na uticnici.

Razdvojene su dvije stvari koje su dotad bile jedna. Rukovanje TLS-om, citanje
zaglavlja i ispis odgovora idu u vise dretvi, jer traju onoliko koliko traje
tudji telefon. Rad nad bazom ostaje serijaliziran, jedan po jedan.

Zasto se rad nad bazom ne pusta u paralelu, iako bi WAL to podnio: javni broj
narudzbe racuna se kao `MAX + 1`, provjera kljuca idempotencije prethodi upisu,
stanje stavke se cita pa mijenja. Takvih mjesta su desetci i nisu oznacena.
Pustiti ih u paralelu znaci prevesti kvar s mreze u kvar u podacima, a podaci
su jedino sto se ne da popraviti ponovnim pokretanjem. Cijena je izgovorena do
kraja: dok jedan zahtjev radi nad bazom, ostali cekaju. Isplati se dok je rad
nad bazom kratak, a mjeri se u desetinkama milisekunde.

Jedino mjesto koje unutar obrade ceka na necem sporom je dohvat javnih kljuceva
vanjskog davatelja prijave. Za njega postoji izlazak iz reda i povratak na istu
dubinu gnijezdenja:

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
dubine jeftinije je od oslanjanja na tudji dogovor s podvlakom. Cijeli modul je
u [`primjer/brava.py`](primjer/brava.py), 117 redaka, uz
[deset testova](testovi/test_brava.py) pisanih za ovaj izlog.

## Verzija sheme zivi u samoj datoteci baze

Naljepnice na stolovima su zalijepljene i na njima stoji identifikator stola.
Obrisana baza znaci nove identifikatore, dakle sve naljepnice u smecu. Zato
nadogradnja mijenja oblik baze a sadrzaj ostavlja na miru.

Verzija se pamti u `PRAGMA user_version`, ne tablicom, iako je tablica
citljivija. Broj je dio datoteke pa putuje s njom: kopija, vracena pricuva i
datoteka prenesena na drugo racunalo nose svoju verziju sa sobom, dok tablica
koju netko zaboravi prepisati laze o tome sto u bazi stoji. Broj se upisuje
unutar transakcije i s njom se povlaci natrag, sto je provjereno a ne
pretpostavljeno, pa se "migracija je izvedena" i "broj je podignut" ne mogu
raziciti. Tablica migracija ipak postoji, ali kao dnevnik za covjeka koji trazi
kvar.

Pricuva prije migracije je obavezna, jer transakcija cuva od prekida ali ne
cuva od migracije koja se uredno potvrdi i pogrijesi. Padne li bilo sto, sustav
prvo pogleda je li baza vec u zatecenom stanju, jer transakcija cesto obavi
posao sama; ako nije, vrati punu pricuvu i provjeri da je vracena datoteka
doista jednaka zatecenoj, ista verzija i isti otisak sadrzaja. Tek tada javlja
gresku.

## Datoteka koja se procita i na krivom Pythonu

Svaka datoteka sustava pocinje s `from __future__ import annotations`. Tu
naredbu stari Python ne poznaje, pa takva datoteka pukne jos pri citanju, prije
nego ijedan njezin redak dobije priliku javiti sto fali. Ishod na tudjem
racunalu je sintaksna greska iz sredine datoteke koju vlasnik nikad nije
otvorio.

Dvije datoteke zato su pisane starom sintaksom, bez f-nizova i bez napomena o
tipovima: ona koja zna inacicu i ona koja provjerava okolinu. One se procitaju i
na Pythonu 2.7 i kazu jednu razumljivu recenicu.

```python
NAJMANJI_PYTHON = (3, 9)          # ispod se ne pokrece
ISPROBAN_PYTHON = (3, 9, 6)       # jedina inacica na kojoj je cijeli skup prosao
NAJVISI_ISPROBAN_PYTHON = (3, 9)  # iznad: upozorenje, ne odbijanje
```

Neisprobano nije isto sto i "vjerojatno radi", pa se ispod granice odbija. Ali
odbiti noviji Python znacilo bi da se sustav ne da isporuciti na racunalo
kupljeno ove godine, pa se iznad granice pusta uz izricitu napomenu da to nitko
nije vidio.

Iz istog razloga sustav se pakira u jednu arhivu od oko 800 kB sa `SHA-256`
popisom i branom protiv putanja s ovog racunala, a prije pokretanja na tudjem
racunalu jedna naredba provjerava Python, cjelovitost isporuke, prava, disk,
vrata i sat.

## Prva brojka inacice ostaje nula

```python
INACICA = "0.9.0"
```

Ostaje nula dok sustav ne odradi jedan cijeli radni dan u stvarnom lokalu, jer
je sve dosad izmjereno izmjereno na razvojnom racunalu, a to nije isto.

Popis onoga sto jos nije napravljeno pripada ovdje jednako kao i ostalo. Nula
lokala i nula gostiju: sav promet dosad je s razvojnog racunala. Linux nikad
nije pokrenut, a Linux je ciljna platforma; jedinice usluge i skripta postave
napisane su ali nikad izvedene. Dugotrajan rad dokazan je na 40 minuta, ne na
dvanaestosatnu smjenu. Put od koda do fizicke oznake nikad nije prosao do kraja.
Citanje kroz stijenku nije izmjereno, pa vrijednost dometa dolazi iz deklaracije
proizvodjaca.

Tehnicka strana je najdalje dosla. Sve sto nedostaje je izvan koda.

## Licenca

Apache-2.0, [LICENSE](LICENSE). Odnosi se na kod i tekst u ovom repozitoriju.
Puni sustav nije objavljen.
