"""Cog display names, pinned against drift.

Every name below was checked twice: it resolves to a canonical page title
on the TTR wiki (not a redirect to one), and it matches the string the
game client itself reports in its summons table.

That double check has already earned its keep four times. "Backstabber"
was one word where the wiki has two, sitting directly under a comment
that said the wiki spelled it as two. "Mover And Shaker", "Two Face" and
"Mr Hollywood" had lost their punctuation, which is invisible until a
name is shown to a player or used to look something up -- all three
resolved to no wiki page at all.

If a name here has to change, change it because a source says so, and say
which source in the commit.
"""
import unittest

from solver import data

# key -> display, as confirmed by both the wiki and the game client.
VERIFIED = {
    # bossbot
    "flunky": "Flunky",
    "pencil_pusher": "Pencil Pusher",
    "yesman": "Yesman",
    "micromanager": "Micromanager",
    "downsizer": "Downsizer",
    "head_hunter": "Head Hunter",
    "corporate_raider": "Corporate Raider",
    "the_big_cheese": "The Big Cheese",
    # cashbot
    "short_change": "Short Change",
    "penny_pincher": "Penny Pincher",
    "tightwad": "Tightwad",
    "bean_counter": "Bean Counter",
    "number_cruncher": "Number Cruncher",
    "money_bags": "Money Bags",
    "loan_shark": "Loan Shark",
    "robber_baron": "Robber Baron",
    # lawbot
    "bottom_feeder": "Bottom Feeder",
    "bloodsucker": "Bloodsucker",
    "double_talker": "Double Talker",
    "ambulance_chaser": "Ambulance Chaser",
    "backstabber": "Back Stabber",
    "spin_doctor": "Spin Doctor",
    "legal_eagle": "Legal Eagle",
    "big_wig": "Big Wig",
    # sellbot
    "cold_caller": "Cold Caller",
    "telemarketer": "Telemarketer",
    "name_dropper": "Name Dropper",
    "glad_hander": "Glad Hander",
    "mover_and_shaker": "Mover & Shaker",
    "two_face": "Two-Face",
    "the_mingler": "The Mingler",
    "mr_hollywood": "Mr. Hollywood",
}


def all_cogs():
    return [cog for dept in data.COG_DEPARTMENTS.values()
            for cog in dept.cogs]


class DisplayNameTest(unittest.TestCase):

    def test_every_cog_has_a_verified_name(self):
        self.assertEqual({c.key for c in all_cogs()}, set(VERIFIED))

    def test_display_names_match_the_verified_spelling(self):
        for cog in all_cogs():
            with self.subTest(cog=cog.key):
                self.assertEqual(cog.display, VERIFIED[cog.key])

    def test_names_are_not_silently_punctuation_stripped(self):
        """The three that broke did so by losing '&', '-' and '.'."""
        self.assertEqual(VERIFIED["mover_and_shaker"], "Mover & Shaker")
        self.assertEqual(VERIFIED["two_face"], "Two-Face")
        self.assertEqual(VERIFIED["mr_hollywood"], "Mr. Hollywood")

    def test_keys_are_slugs(self):
        for cog in all_cogs():
            with self.subTest(cog=cog.key):
                self.assertRegex(cog.key, r"^[a-z][a-z0-9_]*$")

    def test_keys_are_unique_across_departments(self):
        keys = [c.key for c in all_cogs()]
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
