#-------------------------------------------------------------------------------
# elftools tests
#
# Eli Bendersky (eliben@gmail.com)
# This code is in the public domain
#-------------------------------------------------------------------------------
import unittest
import os

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import StabSection


class TestStab(unittest.TestCase):
    def test_stab(self):
        expected = [
            ("obj_stabs.S", 0, 0, 0x2, 33), # generated by compiler
            ("label", 0x95, 0xc8, 0x4072, 0xdeadbeef),
            ("another label", 0x41, 0x66, 0xf9b1, 0xcafebabe)]
        with open(os.path.join('test', 'testfiles_for_unittests',
                               'obj_stabs.elf'), 'rb') as f:
            elf = ELFFile(f)

            # using correct type?
            for s in elf.iter_sections():
                if s.name == '.stab':
                    self.assertIsInstance(s, StabSection)

            # check section contents
            stab = elf.get_section_by_name('.stab')
            stabstr = elf.get_section_by_name('.stabstr')
            for entry, golden in zip(stab.iter_stabs(), expected):
                self.assertEqual(stabstr.get_string(entry.n_strx), golden[0])
                self.assertEqual(entry.n_type, golden[1])
                self.assertEqual(entry.n_other, golden[2])
                self.assertEqual(entry.n_desc, golden[3])
                self.assertEqual(entry.n_value, golden[4])


if __name__ == '__main__':
    unittest.main()
