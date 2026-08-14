"""Testovi za Bravu: reentrantnost, vlasnistvo i izlazak iz reda."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from primjer.brava import Brava  # noqa: E402


def test_ulaz_i_izlaz():
    b = Brava()
    assert b.drzim() is False
    with b:
        assert b.drzim() is True
    assert b.drzim() is False


def test_reentrantnost():
    """Slojevi se gnijezde: nadzor zove upravu, uprava plocu. Da brava
    nije reentrantna, prvi ugnijezdeni sloj zakljucao bi se sam sa sobom."""
    b = Brava()
    with b:
        with b:
            with b:
                assert b.drzim() is True
            assert b.drzim() is True
        assert b.drzim() is True
    assert b.drzim() is False


def test_tudja_dretva_ne_drzi_bravu():
    b = Brava()
    vidjeno = []
    with b:
        t = threading.Thread(target=lambda: vidjeno.append(b.drzim()))
        t.start()
        t.join()
    assert vidjeno == [False]


def test_otpustanje_tudje_brave_je_greska():
    b = Brava()
    b.__enter__()
    greske = []

    def tudja():
        try:
            b.__exit__(None, None, None)
        except RuntimeError as e:
            greske.append(str(e))

    t = threading.Thread(target=tudja)
    t.start()
    t.join()
    b.__exit__(None, None, None)
    assert greske and "ne drzi" in greske[0]


def test_serijalizacija_dvije_dretve():
    """Dvije dretve ne smiju biti unutar brave istovremeno."""
    b = Brava()
    unutra = 0
    najvise = 0
    zakljucaj = threading.Lock()

    def posao():
        nonlocal unutra, najvise
        for _ in range(50):
            with b:
                with zakljucaj:
                    unutra += 1
                    najvise = max(najvise, unutra)
                time.sleep(0.0005)
                with zakljucaj:
                    unutra -= 1

    dretve = [threading.Thread(target=posao) for _ in range(4)]
    for t in dretve:
        t.start()
    for t in dretve:
        t.join()
    assert najvise == 1


def test_predah_pusta_drugu_dretvu():
    """Dok jedna dretva ceka mrezu, druga mora moci uci. Bez toga jedna
    prijava vanjskoj usluzi zaustavi cijeli lokal."""
    b = Brava()
    redoslijed: list[str] = []
    druga_je_usla = threading.Event()

    def druga():
        with b:
            redoslijed.append("druga-usla")
            druga_je_usla.set()

    with b:
        redoslijed.append("prva-u-bravi")
        t = threading.Thread(target=druga)
        t.start()
        with b.predah():
            # Predah je otpustio bravu, pa druga dretva sada smije uci.
            assert druga_je_usla.wait(timeout=2.0), "predah nije pustio drugu dretvu"
            redoslijed.append("prva-ceka-mrezu")
        t.join()
        assert b.drzim() is True, "brava se mora vratiti nakon predaha"
    assert redoslijed == ["prva-u-bravi", "druga-usla", "prva-ceka-mrezu"]


def test_predah_vraca_istu_dubinu():
    """Povratak iz predaha mora vratiti tocno onu dubinu gnijezdenja koja
    je bila, inace ce vanjski sloj otpustiti bravu prerano ili prekasno."""
    b = Brava()
    with b:
        with b:
            with b:
                with b.predah():
                    assert b.drzim() is False
                assert b.drzim() is True
            assert b.drzim() is True
        assert b.drzim() is True
    assert b.drzim() is False


def test_predah_izvan_reda_prolazi_bez_ucinka():
    """Isti kod mora raditi i u testu koji aplikaciju zove izravno, bez
    ogradjivanja. Zato predah dretve koja bravu ne drzi nije greska."""
    b = Brava()
    with b.predah():
        pass
    assert b.drzim() is False


def test_iznimka_unutar_brave_otpusta():
    b = Brava()
    with pytest.raises(ValueError):
        with b:
            raise ValueError("kvar u obradi")
    assert b.drzim() is False
    with b:
        assert b.drzim() is True


def test_iznimka_unutar_predaha_vraca_bravu():
    """Ako mrezni poziv baci iznimku, brava se mora vratiti prije nego
    iznimka izadje iz sloja, inace ostaje otpustena zauvijek."""
    b = Brava()
    with b:
        with pytest.raises(TimeoutError):
            with b.predah():
                raise TimeoutError("vanjska usluga ne odgovara")
        assert b.drzim() is True
    assert b.drzim() is False
