"""The TTR client's log names a boss room the Local API does not."""
import os
import tempfile
import time
import unittest

from solver.live import boss, ttr_log

# Real lines from a 2026-10-10 session, unchanged.
VP = (":vltf777d7a2: enter(requestStatus={'loader': 'CogHQLoader', 'where': "
      "'CogHQBossBattle', 'how': 'Movie', 'zoneId': 177131, 'hoodId': 11000})")
BUILDING = (":vltf777d7a2: enter(requestStatus={'loader': 'SuitInterior', "
            "'where': 'SuitInterior', 'hoodId': 3000, 'zoneId': 3728, 'shardId': None})")
PLAYGROUND = (":vltf777d7a2: enter(requestStatus={'loader': 'SafeZoneLoader', "
              "'where': 'Playground', 'how': 'TeleportIn', 'hoodId': "
              "<vlt63adacc8.vlt9070e393: 5000>, 'zoneId': "
              "<vlt63adacc8.vlt9070e393: 5000>, 'shardId': None, 'avId': -1})")
NL = "\n"


class ParseTest(unittest.TestCase):

    def test_the_real_lines(self):
        self.assertEqual(("CogHQBossBattle", 11000), ttr_log.parse_place(VP))
        self.assertEqual(("SuitInterior", 3000), ttr_log.parse_place(BUILDING))
        self.assertEqual(("Playground", 5000), ttr_log.parse_place(PLAYGROUND))
        self.assertIsNone(ttr_log.parse_place(":audio(error): Cannot open file"))

    def test_only_the_observed_room_names_a_fight(self):
        self.assertEqual("vp", boss.boss_from_place("CogHQBossBattle", 11000))
        self.assertIsNone(boss.boss_from_place("CogHQBossBattle", 12000),
                          "the CFO's room is [TODO] until observed")
        self.assertIsNone(boss.boss_from_place("SuitInterior", 3000))


class WatcherTest(unittest.TestCase):

    def test_it_follows_the_newest_log_incrementally(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ttr-261010_200413_1.log")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(PLAYGROUND + NL)
            w = ttr_log.PlaceWatcher(d)
            self.assertEqual(("Playground", 5000), w.place())
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("noise" + NL + VP + NL)
            self.assertEqual(("CogHQBossBattle", 11000), w.place())
            self.assertEqual(("CogHQBossBattle", 11000), w.place(),
                             "no new line, same place")
            time.sleep(0.05)
            newer = os.path.join(d, "ttr-261010_210237_2.log")
            with open(newer, "w", encoding="utf-8") as fh:
                fh.write(BUILDING + NL)
            later = time.time() + 5
            os.utime(newer, (later, later))
            self.assertEqual(("SuitInterior", 3000), w.place())

    def test_no_install_is_none_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(ttr_log.PlaceWatcher(os.path.join(d, "absent")).place())


if __name__ == "__main__":
    unittest.main()
