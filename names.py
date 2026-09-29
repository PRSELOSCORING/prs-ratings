"""Name matching helpers: shooter ids are the identity; names only link a brand-new id to an existing rating."""
import difflib, re
from prs_rating_engine import normalize_name as nz

NICKNAMES = {
    "matt": "matthew", "dan": "daniel", "danny": "daniel", "mike": "michael", "chris": "christopher",
    "nick": "nicholas", "nate": "nathan", "josh": "joshua", "jon": "jonathan", "jonny": "jonathan",
    "johnny": "john", "jim": "james", "jimmy": "james", "bill": "william", "will": "william",
    "billy": "william", "bob": "robert", "rob": "robert", "bobby": "robert", "tom": "thomas",
    "tommy": "thomas", "tony": "anthony", "andy": "andrew", "drew": "andrew", "steve": "steven",
    "joe": "joseph", "joey": "joseph", "ben": "benjamin", "sam": "samuel", "zach": "zachary",
    "zack": "zachary", "alex": "alexander", "jeff": "jeffrey", "greg": "gregory", "rick": "richard",
    "rich": "richard", "ken": "kenneth", "kenny": "kenneth", "tim": "timothy", "jake": "jacob",
    "ed": "edward", "eddie": "edward", "ron": "ronald", "don": "donald", "pat": "patrick",
    "dave": "david", "doug": "douglas", "fred": "frederick", "jerry": "gerald", "larry": "lawrence",
    "charlie": "charles", "chuck": "charles",
}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v", "1", "2", "3"}


def key(name):
    """Exact identity key: case/whitespace-insensitive (also folds non-breaking spaces)."""
    return nz(name)


def loose_key(name):
    """Looser key for spotting the same person: drop punctuation and suffixes, expand nicknames."""
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", nz(name)).split() if w not in SUFFIXES]
    if words:
        words[0] = NICKNAMES.get(words[0], words[0])
    return " ".join(words)


def _swap_sig(k):
    """'havid doff' and 'david hoff' share this signature (first letters of the two words swapped)."""
    w = k.split()
    return (w[0][1:], w[1][1:], frozenset((w[0][:1], w[1][:1]))) if len(w) == 2 else None


class Matcher:
    """Looks up possible existing names for a new shooter. Build once, query many times."""

    def __init__(self, names):
        self.by_key, self.by_loose, self.by_swap = {}, {}, {}
        for n in names:
            k = key(n)
            self.by_key.setdefault(k, n)
            self.by_loose.setdefault(loose_key(n), []).append(n)
            s = _swap_sig(k)
            if s: self.by_swap.setdefault(s, []).append(n)
        self.keys = list(self.by_key)

    def suggest(self, name, exclude=(), cutoff=0.85):
        """(existing_name, reason, auto_link) or None. auto_link only for unambiguous nickname/suffix matches."""
        k = key(name)
        loose = [c for c in self.by_loose.get(loose_key(name), []) if key(c) != k and key(c) not in exclude]
        if len(loose) == 1:
            return loose[0], "nickname / suffix / punctuation", True
        s = _swap_sig(k)
        for c in self.by_swap.get(s, []) if s else []:
            if key(c) != k and key(c) not in exclude:
                return c, "swapped letters", False
        for c in difflib.get_close_matches(k, self.keys, n=3, cutoff=cutoff):
            if c != k and c not in exclude:
                ratio = difflib.SequenceMatcher(None, k, c).ratio()
                return self.by_key[c], f"similar spelling ({ratio:.0%})", False
        return None
