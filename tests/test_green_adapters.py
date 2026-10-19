import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scraper'))
from shared_parser import SHARED_ROOT
from scraper.green import parse_detail, source_infographic
from scraper.catalog import CatalogError
import match_watchlist


def load(name):
    spec = importlib.util.spec_from_file_location('adapter_' + name, ROOT / 'scraper' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SM = load('scrape')
CBC = load('scrape_cbc')
HACEA = load('scrape_hacea')
ROYAL = load('scrape_royal')
GO = load('scrape_genuineorigin')
FIXTURES = SHARED_ROOT / 'tests/fixtures/green'


def fixture(source):
    return parse_detail(source, (FIXTURES / f'{source}.html').read_text())


def test_sweetmarias_existing_schema_keeps_zero_flavor_scores():
    record = SM.build_record({'name':'Yemen Lot','url':'https://example.com/products/lot',
                             'price':'$10','origin_category':''}, fixture('sweetmarias'))
    assert record['country'] == 'Yemen'
    assert record['total_score'] == '87.8'
    assert record['cupping_dry_fragrance'] == '8.2'
    assert record['flavor_floral'] == '0'
    assert record['recommended_for_espresso'] == 'Yes'


def test_hacea_current_keys_populate_existing_schema():
    record = HACEA.build_record({'name':'Brazil Lot','url':'https://example.com/products/lot', 'price':'$7.03'}, fixture('hacea'))
    assert record['price'] == '$7.03'
    assert record['harvest_date'] == 'September 2025'
    assert record['sca_cupping_score'] == '83.75'
    assert record['varieties'].startswith('Various')


def test_cbc_scores_and_specs_populate_existing_schema():
    record = CBC.build_record({'name':'Ethiopia Lot','url':'https://example.com/products/lot','price':'$10.25'}, fixture('cbc'))
    assert record['attr_brightness'] == '5'
    assert record['flavor_chocolaty'] == '4'
    assert record['process'] == 'Natural'


def test_royal_per_pound_not_divided_twice():
    detail = fixture('royal')
    detail.update(jsonld_price='789.62', jsonld_weight_unit='LBR')
    record = ROYAL.build_record({'url':'https://example.com/products/lot','bag_type':'Full Bag'}, detail, set())
    assert record['price_per_lb'] == '$5.20'
    assert record['total_price'] == '$789.62'
    assert record['warehouse'] == 'Oakland'


def test_royal_crown_box_price_and_structured_specs():
    detail = parse_detail('royal', (FIXTURES / 'royal-crown.html').read_text())
    detail.update(source_infographic(json.loads((FIXTURES / 'royal-source.json').read_text())))
    detail.update(jsonld_price='314.34', jsonld_weight='22', jsonld_weight_unit='LBR')
    record = ROYAL.build_record({'url':'https://example.com/products/lot','bag_type':'Crown Jewel'}, detail, set())
    assert record['price_per_lb'] == '$14.29'
    assert record['variety'] == 'Typica'
    assert record['source_text'].startswith('Source')


@pytest.mark.parametrize('value', ['NaN','Infinity',-1,0,None,''])
def test_genuineorigin_invalid_prices(value):
    assert GO.format_price(value) == ''
    assert GO.format_price_per_pound(value) == ''


def item(index):
    return {'internalid':index}


def test_genuineorigin_paginates_without_total(monkeypatch):
    monkeypatch.setattr(GO,'PAGE_SIZE',2)
    monkeypatch.setattr(GO.time,'sleep',lambda _: None)
    monkeypatch.setattr(GO,'get',Mock(side_effect=[Mock(json=lambda: {'items':[item(1),item(2)]}), Mock(json=lambda: {'items':[item(3)]})]))
    assert len(GO.fetch_all_items()) == 3


def test_genuineorigin_partial_response_fails(monkeypatch):
    monkeypatch.setattr(GO,'get',lambda *a,**k: Mock(json=lambda: {'items':[item(1)],'total':1000}))
    with pytest.raises(CatalogError,match='ended'):
        GO.fetch_all_items()


def test_genuineorigin_packages_only_list_available_sizes():
    assert GO.package_sizes({'matrixchilditems_detail':[
        {'custitem_go_matrix_package':'65lb box','isinstock':False},
        {'custitem_go_matrix_package':'Sample','isinstock':True},
    ]}) == 'Sample'


def test_watchlist_requires_explicit_identity_and_compatible_country(monkeypatch):
    monkeypatch.setattr(match_watchlist,'load_watchlist',lambda:[{'producer_name':'Diego Bermudez','farm_or_station':'Finca El Paraiso','country':'Colombia','tier':'Elite'}])
    records=[{'name':'Diego Bermudez lot','country':'Colombia'},
             {'name':'Finca El Paraiso','country':'Honduras'},
             {'name':'A Colombian coffee','country':'Colombia'}]
    match_watchlist.match_products(records,['name','country'])
    assert records[0]['watchlist_tier'] == 'Elite'
    assert records[1]['watchlist_match'] == records[2]['watchlist_match'] == ''


def test_optional_royal_llm_does_not_cache_malformed_success():
    extractor = load('extract_royal')
    with pytest.raises(ValueError):
        extractor._parse_llm_response('not JSON')


@pytest.mark.parametrize('bad_price', ['NaN', 0, '', None])
def test_genuineorigin_bad_coffee_price_preserves_published_dataset(monkeypatch, tmp_path, bad_price):
    output = tmp_path / 'genuineorigin-data.json'
    output.write_text('[{"old": true}]')
    items = [{'storedisplayname2': f'Coffee {i}', 'custitemorigin': 'Colombia',
              'urlcomponent': f'coffee-{i}', 'custitem_price_per_pound': 8}
             for i in range(20)]
    items[10]['custitem_price_per_pound'] = bad_price
    monkeypatch.setattr(GO, 'fetch_all_items', lambda: items)
    monkeypatch.setattr(GO, 'JSON_FILE', output)
    csv_writer, json_writer, matcher = Mock(), Mock(), Mock()
    monkeypatch.setattr(GO, 'write_csv', csv_writer)
    monkeypatch.setattr(GO, 'write_json', json_writer)
    monkeypatch.setattr(GO, 'match_products', matcher)
    with pytest.raises(CatalogError, match='Invalid price'):
        GO.main()
    csv_writer.assert_not_called()
    json_writer.assert_not_called()
    matcher.assert_not_called()
    assert output.read_text() == '[{"old": true}]'


def test_royal_json_writer_preserves_distinct_lot_urls(monkeypatch, tmp_path):
    output = tmp_path / 'royal-data.json'
    monkeypatch.setattr(ROYAL, 'JSON_FILE', output)
    records = [{'name': 'Colombia Lot', 'warehouse': 'Oakland', 'price_per_lb': '$6.00',
                'url': f'https://example.com/products/{lot}'} for lot in ['old', 'new']]
    ROYAL.write_json(records)
    assert json.loads(output.read_text()) == records


def test_farm_only_watchlist_matches_have_a_display_identity(monkeypatch):
    monkeypatch.setattr(match_watchlist, 'load_watchlist', lambda: [
        {'producer_name': '', 'farm_or_station': 'Finca El Diviso', 'country': 'Colombia', 'tier': 'WBC Elite'}])
    records = [{'name': 'Finca El Diviso Java', 'country': 'Colombia'},
               {'name': 'Finca El Diviso Java', 'country': 'Honduras'}]
    match_watchlist.match_products(records, ['name', 'country'])
    assert records[0]['watchlist_match'] == records[0]['watchlist_farm'] == 'Finca El Diviso'
    assert records[0]['watchlist_tier'] == 'WBC Elite'
    assert records[1]['watchlist_match'] == ''
