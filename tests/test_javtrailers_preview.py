import unittest

from peach import javtrailers_preview as jt


class JavTrailersSlugTests(unittest.TestCase):
    def test_standard_codes_are_five_digit_padded(self):
        self.assertEqual(jt.standard_slug('MIDA-859'), 'mida00859')
        self.assertEqual(jt.standard_slug('AARM-372'), 'aarm00372')
        self.assertEqual(jt.standard_slug('MYBA-097'), 'myba00097')
        self.assertEqual(jt.standard_slug('mida-859'), 'mida00859')

    def test_non_standard_codes_have_no_direct_slug(self):
        self.assertEqual(jt.standard_slug('h_1729goji00120'), '')
        self.assertEqual(jt.standard_slug('FC2-PPV-1234567'), '')

    def test_normalized_code_ignores_case_and_punctuation(self):
        self.assertEqual(jt.normalized_code('mida-859'), 'MIDA859')
        self.assertEqual(jt.normalized_code('MIDA 859'), 'MIDA859')


class JavTrailersPageTests(unittest.TestCase):
    PAGE = '''
      <p><span class="font-weight-bold mr-3">DVD ID:</span> MIDA-859</p>
      <video src="https://media.javtrailers.com/hlsvideo/freepv/m/mid/mida00859/playlist.m3u8"></video>
    '''

    def test_dvd_id_matches_after_normalization(self):
        self.assertTrue(jt._matches(self.PAGE, 'MIDA-859'))
        self.assertTrue(jt._matches(self.PAGE, 'mida 859'))
        self.assertFalse(jt._matches(self.PAGE, 'MIDA-849'))

    def test_media_url_is_the_master_playlist(self):
        self.assertEqual(
            jt._video(self.PAGE),
            'https://media.javtrailers.com/hlsvideo/freepv/m/mid/mida00859/playlist.m3u8')
        self.assertEqual(jt._video('<p>no video</p>'), '')


if __name__ == '__main__':
    unittest.main()
