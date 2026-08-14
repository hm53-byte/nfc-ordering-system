"""Jedan po jedan u bazu, svi odjednom na mrezi.

Ovaj modul postoji zbog jedne izmjerene stvari. Posluzitelj je bio
jednonitan, pa se svako cekanje na MREZI zbrajalo: pet veza koje posalju
nedovrseno zaglavlje i sute drzale su normalnog gosta 24,5 s (mjereno
9.8.2026., uz rok od 5 s po vezi), a pedeset njih preko cetiri minute.
Uzrok nije bila baza nego to sto je jedna nit cekala na uticnici.

Rjesenje je razdvojiti dvije stvari koje su dosad bile jedna:

- CEKANJE NA MREZI ide u vise dretvi. Rukovanje TLS-om, citanje
  zaglavlja, citanje tijela i ispis odgovora traju onoliko koliko traje
  tudji telefon, i ne smiju nikoga drugoga drzati.
- RAD NAD BAZOM ostaje serijaliziran, jedan po jedan, i to je ono sto
  ovaj modul provodi.

Zasto se rad nad bazom NE pusta u paralelu, iako bi WAL to podnio:
cijeli je sustav gradjen na tome da izmedju citanja i pisanja nitko ne
umetne svoj upis. Javni broj narudzbe se racuna kao MAX + 1, provjera
kljuca idempotencije prethodi upisu, stanje stavke se cita pa mijenja.
Takvih mjesta su desetci i nisu oznacena, jer dosad nisu morala biti.
Pustiti ih u paralelu znaci prevesti kvar s mreze u kvar u podacima, a
podaci su jedino sto se ne da popraviti ponovnim pokretanjem.

Cijena je izgovorena do kraja: dok jedan zahtjev radi nad bazom, ostali
cekaju. To se isplati samo dok je rad nad bazom kratak, a jest: mjeri se
u desetinkama milisekunde. Jedino mjesto u cijelom sustavu koje unutar
obrade ceka na necemu SPOROM je dohvat Googleovih javnih kljuceva
(prijava.py, urllib s rokom od 5 s). Za njega postoji predah(): izlazak
iz reda dok se ceka mreza, i povratak poslije. Bez toga bi jedna prijava
Googleom zaustavila lokal na pet sekundi, dakle tocno onaj kvar zbog
kojeg je ovaj modul napisan.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

__all__ = ["Brava"]


class Brava:
    """Reentrantna brava oko jedne veze na bazu, s izlaskom iz reda.

    Reentrantna je zato sto se sloj obrade gnijezdi: nadzor prosljedjuje
    upravi, uprava ploci, ploca gostu, a svaki od tih slojeva svoj ulaz
    ogradjuje sam. Da brava nije reentrantna, prvi ugnijezdeni sloj bi se
    zakljucao sam sa sobom.

    Zasto vlastita izvedba, a ne threading.RLock: treba predah(), dakle
    potpuni izlazak iz reda bez obzira na dubinu gnijezdenja i povratak
    na istu dubinu. RLock to zna (_release_save), ali samo kroz privatne
    metode koje postoje radi Conditiona i nisu obecane. Dvadeset redaka
    vlastitog broja dubine je jeftinije od oslanjanja na tudji podvlaka
    dogovor.
    """

    def __init__(self) -> None:
        self._brava = threading.Lock()
        # Cita se i izvan brave, namjerno. Upisuje ga samo dretva koja
        # bravu drzi, pa tudja dretva moze procitati zastarjelu
        # vrijednost, ali nikad SVOJ identifikator koji ondje ne stoji.
        # Zastarjelo citanje vodi na acquire(), sto je ispravan ishod.
        self._vlasnik = None
        self._dubina = 0

    def __enter__(self) -> "Brava":
        ja = threading.get_ident()
        if self._vlasnik == ja:
            self._dubina += 1
            return self
        self._brava.acquire()
        self._vlasnik = ja
        self._dubina = 1
        return self

    def __exit__(self, *_) -> bool:
        if self._vlasnik != threading.get_ident():
            raise RuntimeError("bravu otpusta dretva koja je ne drzi")
        self._dubina -= 1
        if self._dubina == 0:
            self._vlasnik = None
            self._brava.release()
        return False

    def drzim(self) -> bool:
        """Drzi li bravu dretva koja pita; sluzi provjerama i testovima."""
        return self._vlasnik == threading.get_ident()

    @contextmanager
    def predah(self) -> Iterator[None]:
        """Izlazak iz reda dok se ceka nesto sporo, pa povratak na isto.

        Smije se pozvati SAMO kad nije otvorena transakcija nad bazom.
        Unutar transakcije bi otpustanje brave pustilo drugu dretvu na
        istu vezu, a ta bi tudji BEGIN IMMEDIATE zatekla otvorenim i
        upisala svoje retke u tudju transakciju.

        Poziv izvan reda (dretva koja bravu ne drzi) prolazi bez ucinka,
        pa se pozivatelj ne mora pitati je li ogradjen: tako isti kod radi
        i u testu koji aplikaciju zove izravno.
        """
        if self._vlasnik != threading.get_ident():
            yield
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
            self._dubina = dubina
