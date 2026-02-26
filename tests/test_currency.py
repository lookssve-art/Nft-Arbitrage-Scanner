"""Tests for currency conversion (unit tests with mocked API calls)."""

from unittest.mock import patch, MagicMock

from scanner.currency import (
    _cache,
    convert_to_eur,
    sol_to_eur,
    usdc_to_eur,
)


def _mock_sol_response():
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"solana": {"usd": 150.0}}
    mock.raise_for_status = MagicMock()
    return mock


def _mock_eur_response():
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"rates": {"EUR": 0.92}}
    mock.raise_for_status = MagicMock()
    return mock


@patch("scanner.currency.requests.get")
def test_sol_to_eur(mock_get):
    _cache.clear()
    mock_get.side_effect = [_mock_sol_response(), _mock_eur_response()]
    result = sol_to_eur(1.0)
    # 1 SOL * $150 * 0.92 = €138.00
    assert abs(result - 138.0) < 0.01


@patch("scanner.currency.requests.get")
def test_usdc_to_eur(mock_get):
    _cache.clear()
    mock_get.return_value = _mock_eur_response()
    result = usdc_to_eur(100.0)
    # 100 USDC * 0.92 = €92.00
    assert abs(result - 92.0) < 0.01


@patch("scanner.currency.requests.get")
def test_convert_to_eur_sol(mock_get):
    _cache.clear()
    mock_get.side_effect = [_mock_sol_response(), _mock_eur_response()]
    result = convert_to_eur(2.0, "SOL")
    # 2 SOL * $150 * 0.92 = €276.00
    assert abs(result - 276.0) < 0.01


@patch("scanner.currency.requests.get")
def test_convert_to_eur_usdc(mock_get):
    _cache.clear()
    mock_get.return_value = _mock_eur_response()
    result = convert_to_eur(50.0, "USDC")
    # 50 * 0.92 = €46.00
    assert abs(result - 46.0) < 0.01
