import sys; sys.path.insert(0,'.')
from memebot import brand_fake, entry_pumped
def test_brand():
    for s,n in [("AAPLCAT",""),("Apple",""),("NVIDIA",""),("TESLA SI",""),("Gemini",""),("USDF",""),("X T O",""),("xyz","Tesla Inu")]: assert brand_fake(s,n)
    for s in ["PAWCAT","BONK","WIF","JUP"]: assert not brand_fake(s,"")
def test_pumped():
    assert entry_pumped({"priceChange":{"h1":"60"}},{})
    assert not entry_pumped({"priceChange":{"h1":40}},{})
    assert not entry_pumped({},{})
    assert entry_pumped({"priceChange":{"h1":31}},{"max_entry_h1_pct":30})
