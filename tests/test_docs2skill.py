import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from docs2skill import (
    convert_html_to_markdown,
    get_all_links,
    normalize_url,
    postprocess_resource_files,
    remove_markdown_chrome,
)


class Docs2SkillTests(unittest.TestCase):
    def test_normalize_url_removes_fragments(self):
        self.assertEqual(
            normalize_url('https://example.com/docs/page?tab=web#setup'),
            'https://example.com/docs/page?tab=web'
        )

    @patch('docs2skill.requests.get')
    def test_get_all_links_deduplicates_fragments(self, mock_get):
        response = Mock()
        response.content = b'''
            <a href="/docs/page#one">One</a>
            <a href="/docs/page#two">Two</a>
        '''
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        links = get_all_links('https://example.com/docs/')

        self.assertEqual(links, {'https://example.com/docs/page'})

    def test_convert_html_to_markdown_removes_documentation_chrome(self):
        markdown = convert_html_to_markdown(b'''
            <html><body>
              <a class="skip-main">Skip to content</a>
              <div id="nav_bar">Documentation menu</div>
              <div class="copy-for-llm-page-header">Copy for LLM</div>
              <a id="cc_prompt">New Stuff!</a>
              <article><h1>Useful content</h1><p>Keep this.</p></article>
            </body></html>
        ''')

        self.assertIn('Useful content', markdown)
        self.assertIn('Keep this.', markdown)
        self.assertNotIn('Skip to content', markdown)
        self.assertNotIn('Documentation menu', markdown)
        self.assertNotIn('Copy for LLM', markdown)
        self.assertNotIn('New Stuff!', markdown)

    def test_remove_markdown_chrome_cleans_legacy_resources(self):
        markdown = '''Skip to content

![](/docs/assets/img/sidebar-rail-collapse.svg) Press Arrow down to open the documentation menu without expanding the sidebar.

Press `Esc` to close the menu

# Keep this heading

Keep this paragraph.

__ Back to top
'''

        cleaned = remove_markdown_chrome(markdown)

        self.assertIn('# Keep this heading', cleaned)
        self.assertIn('Keep this paragraph.', cleaned)
        self.assertNotIn('Skip to content', cleaned)
        self.assertNotIn('sidebar-rail-collapse.svg', cleaned)
        self.assertNotIn('Press `Esc`', cleaned)
        self.assertNotIn('Back to top', cleaned)

    def test_postprocess_deduplicates_fragments_and_adds_contents(self):
        repeated_body = '\n'.join(f'Line {index}' for index in range(120))
        content = f'''# Example

## Page

**Source:** https://example.com/docs/page#one

{repeated_body}

---

## Page

**Source:** https://example.com/docs/page#two

{repeated_body}
'''

        with tempfile.TemporaryDirectory() as temporary_directory:
            resources = Path(temporary_directory) / 'resources'
            resources.mkdir()
            resource = resources / 'example.md'
            resource.write_text(content)

            stats = postprocess_resource_files(temporary_directory)
            repaired = resource.read_text()
            second_stats = postprocess_resource_files(temporary_directory)

        self.assertEqual(stats['duplicates_removed'], 1)
        self.assertEqual(stats['contents_added'], 1)
        self.assertEqual(repaired.count('**Source:**'), 1)
        self.assertIn('## Contents', repaired)
        self.assertNotIn('#one', repaired)
        self.assertNotIn('#two', repaired)
        self.assertEqual(second_stats['files_updated'], 0)

    def test_postprocess_deduplicates_identical_content_from_query_urls(self):
        repeated_body = '\n'.join(f'Line {index}' for index in range(120))
        content = f'''# Example

## First tab

**Source:** https://example.com/docs/page?tab=first

{repeated_body}

---

## Second tab

**Source:** https://example.com/docs/page?tab=second

{repeated_body}
'''

        with tempfile.TemporaryDirectory() as temporary_directory:
            resources = Path(temporary_directory) / 'resources'
            resources.mkdir()
            resource = resources / 'example.md'
            resource.write_text(content)

            stats = postprocess_resource_files(temporary_directory)
            repaired = resource.read_text()

        self.assertEqual(stats['duplicates_removed'], 1)
        self.assertEqual(repaired.count('**Source:**'), 1)
        self.assertIn('?tab=first', repaired)
        self.assertNotIn('?tab=second', repaired)


if __name__ == '__main__':
    unittest.main()
