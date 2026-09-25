import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sanitize


class HtmlStrippingTests(unittest.TestCase):
    def test_strips_raw_html_tags(self):
        out = sanitize.sanitize_markdown("before <script>alert(1)</script> after")
        self.assertNotIn("<script>", out)
        self.assertIn("before", out)
        self.assertIn("after", out)

    def test_strips_html_comments(self):
        out = sanitize.sanitize_markdown("a <!-- hidden instruction --> b")
        self.assertNotIn("<!--", out)
        self.assertNotIn("hidden instruction", out)


class ImageTests(unittest.TestCase):
    def test_drops_markdown_images(self):
        out = sanitize.sanitize_markdown("see ![chart](https://evil.example/x.png) here")
        self.assertNotIn("![", out)
        self.assertNotIn("evil.example", out)


class MentionNeutralizationTests(unittest.TestCase):
    def test_neutralizes_at_mentions(self):
        out = sanitize.sanitize_markdown("cc @someone please review")
        self.assertNotIn("@someone", out)
        self.assertIn("someone", out)
        self.assertIn("@" + sanitize.ZERO_WIDTH_SPACE, out)


class IssueRefNeutralizationTests(unittest.TestCase):
    def test_neutralizes_hash_references(self):
        out = sanitize.sanitize_markdown("fixes #123 and relates to #456")
        self.assertNotIn("#123", out)
        self.assertNotIn("#456", out)
        self.assertIn("123", out)
        self.assertIn("#" + sanitize.ZERO_WIDTH_SPACE, out)


class AlertSyntaxNeutralizationTests(unittest.TestCase):
    def test_neutralizes_any_alert_keyword(self):
        for kw in ("NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION"):
            out = sanitize.sanitize_markdown(f"[!{kw}]")
            self.assertNotIn(f"[!{kw}]", out)
            self.assertIn(kw, out)


class LinkAllowlistTests(unittest.TestCase):
    def test_keeps_allowed_host_link(self):
        text = "[topic](https://governance.aave.com/t/x/123)"
        out = sanitize.sanitize_markdown(text)
        self.assertEqual(out, text)

    def test_keeps_allowed_subdomain_link(self):
        text = "[tx](https://optimistic.etherscan.io/tx/0xabc)"
        out = sanitize.sanitize_markdown(text)
        self.assertEqual(out, text)

    def test_delinks_disallowed_host_keeping_text(self):
        out = sanitize.sanitize_markdown("[click here](https://evil.example/phish)")
        self.assertNotIn("evil.example", out)
        self.assertNotIn("](", out)
        self.assertIn("click here", out)

    def test_delinks_disallowed_host_with_empty_text_drops_the_url(self):
        out = sanitize.sanitize_markdown("[](https://evil.example/phish)")
        self.assertNotIn("](", out)
        self.assertNotIn("evil.example", out)
        self.assertEqual(out, "")

    def test_delinks_disallowed_host_with_a_title(self):
        out = sanitize.sanitize_markdown('[click here](https://evil.example/phish "title")')
        self.assertNotIn("evil.example", out)
        self.assertIn("click here", out)

    def test_delinks_disallowed_reference_style_link(self):
        text = "[click here][1]\n\n[1]: https://evil.example/phish"
        out = sanitize.sanitize_markdown(text)
        self.assertNotIn("evil.example", out)
        self.assertIn("click here", out)

    def test_keeps_allowed_reference_style_link(self):
        text = "[tx][1]\n\n[1]: https://etherscan.io/tx/0xabc"
        out = sanitize.sanitize_markdown(text)
        self.assertEqual(out, text)

    def test_neutralizes_bare_url_to_disallowed_host(self):
        out = sanitize.sanitize_markdown("see https://evil.example/phish for details")
        self.assertNotIn("evil.example", out)

    def test_keeps_bare_url_to_allowed_host(self):
        text = "see https://etherscan.io/address/0x1 for details"
        out = sanitize.sanitize_markdown(text)
        self.assertEqual(out, text)


class TruncationTests(unittest.TestCase):
    def test_truncates_to_max_len(self):
        out = sanitize.sanitize_markdown("x" * 100, max_len=10)
        self.assertEqual(len(out), 10)


class OrderingTests(unittest.TestCase):
    def test_images_are_dropped_before_link_delinking_could_leak_their_alt_text(self):
        # If link-delinking ran before image-dropping, the image's inner
        # "[alt](url)" shape would be treated as an ordinary link, and the
        # disallowed-host rule would turn it into a bare "alt" leak instead
        # of the whole image (alt text included) being dropped.
        out = sanitize.sanitize_markdown("![secret plan](https://evil.example/x.png)")
        self.assertNotIn("secret plan", out)
        self.assertNotIn("evil.example", out)

    def test_all_rules_compose_on_one_input(self):
        text = (
            "<!-- injected --> Hi @bob, see #99 and "
            "![img](https://evil.example/a.png) plus "
            "[good](https://etherscan.io/address/0x1) and "
            "[bad](https://evil.example/b)"
        )
        out = sanitize.sanitize_markdown(text)
        self.assertNotIn("<!--", out)
        self.assertNotIn("@bob", out)
        self.assertIn("bob", out)
        self.assertNotIn("#99", out)
        self.assertNotIn("![", out)
        self.assertIn("https://etherscan.io/address/0x1", out)
        self.assertNotIn("evil.example", out)
        self.assertIn("bad", out)


if __name__ == "__main__":
    unittest.main()
