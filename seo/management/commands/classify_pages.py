"""
Management command to classify page roles (hub/spoke/supporting/orphan) for a site.

Usage:
    python manage.py classify_pages --site_id=5
"""
from django.core.management.base import BaseCommand

from integrations.page_classifier import classify_all_pages_roles
from sites.models import Site


class Command(BaseCommand):
    help = 'Classify all pages in a site into hub/spoke/supporting/orphan roles'

    def add_arguments(self, parser):
        parser.add_argument('--site_id', type=int, required=True, help='Site ID to classify')

    def handle(self, *args, **options):
        site_id = options['site_id']
        try:
            site = Site.objects.get(id=site_id)
        except Site.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'Site {site_id} not found'))
            return

        self.stdout.write(f'Classifying pages for site: {site.name} (ID={site_id})')
        results = classify_all_pages_roles(site)

        role_counts = {}
        for r in results:
            role_counts[r['role']] = role_counts.get(r['role'], 0) + 1

        self.stdout.write(self.style.SUCCESS(f'Classified {len(results)} pages'))
        for role, count in sorted(role_counts.items()):
            self.stdout.write(f'  {role}: {count}')
