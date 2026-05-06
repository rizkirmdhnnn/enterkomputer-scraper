"""Unit tests for the offline portions of src.discover."""
from src.discover import parse_sitemap


SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://enterkomputer.com/</loc></url>
  <url><loc>https://enterkomputer.com/faq/how_to_buy</loc></url>
  <url><loc>https://enterkomputer.com/category/17/processor</loc></url>
  <url><loc>https://enterkomputer.com/category_brand/17/processor/intel</loc></url>
  <url><loc>https://enterkomputer.com/subcategory/17/processor/desktop</loc></url>
  <url><loc>https://enterkomputer.com/keyword/17/processor/Core%20i5</loc></url>
  <url><loc>https://enterkomputer.com/detail/180977/some-product</loc></url>
  <url><loc>https://enterkomputer.com/brand/sapphire</loc></url>
</urlset>
"""


def test_parse_sitemap_returns_listings_and_products():
    listings, products = parse_sitemap(SITEMAP_XML)
    # /category/, /subcategory/, /category_brand/ are listings
    assert "https://enterkomputer.com/category/17/processor" in listings
    assert "https://enterkomputer.com/category_brand/17/processor/intel" in listings
    assert "https://enterkomputer.com/subcategory/17/processor/desktop" in listings
    # /detail/ is a product
    assert "https://enterkomputer.com/detail/180977/some-product" in products
    # /keyword/ is excluded (subset of categories)
    assert all("/keyword/" not in u for u in listings)
    # Homepage, faq, and /brand/ aren't useful listings
    assert all("/faq/" not in u for u in listings)
    assert all(u != "https://enterkomputer.com/" for u in listings)


def test_parse_sitemap_dedupes():
    xml = """<?xml version="1.0"?><urlset>
        <url><loc>https://enterkomputer.com/category/17/processor</loc></url>
        <url><loc>https://enterkomputer.com/category/17/processor</loc></url>
    </urlset>"""
    listings, products = parse_sitemap(xml)
    assert len(listings) == len(set(listings))


def test_parse_sitemap_handles_empty():
    xml = '<?xml version="1.0"?><urlset></urlset>'
    listings, products = parse_sitemap(xml)
    assert listings == []
    assert products == []
