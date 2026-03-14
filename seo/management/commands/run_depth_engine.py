"""
Management command to run depth engine jobs:
  - Daily freshness monitor
  - Weekly depth scan
  - Decay log cleanup

Usage:
  python manage.py run_depth_engine              # runs all
  python manage.py run_depth_engine --freshness   # daily freshness only
  python manage.py run_depth_engine --depth-scan  # weekly depth scan only
  python manage.py run_depth_engine --purge       # purge old decay logs only
"""
from django.core.management.base import BaseCommand

from seo.depth_engine import purge_old_decay_logs, run_freshness_monitor, run_weekly_depth_scan


class Command(BaseCommand):
    help = 'Run Topical Depth Engine jobs: freshness monitor, depth scan, decay log cleanup'

    def add_arguments(self, parser):
        parser.add_argument('--freshness', action='store_true', help='Run daily freshness monitor only')
        parser.add_argument('--depth-scan', action='store_true', help='Run weekly depth scan only')
        parser.add_argument('--purge', action='store_true', help='Purge resolved decay logs older than 90 days')

    def handle(self, *args, **options):
        run_all = not (options['freshness'] or options['depth_scan'] or options['purge'])

        if run_all or options['freshness']:
            self.stdout.write('Running freshness monitor...')
            run_freshness_monitor()
            self.stdout.write(self.style.SUCCESS('Freshness monitor complete.'))

        if run_all or options['depth_scan']:
            self.stdout.write('Running weekly depth scan...')
            run_weekly_depth_scan()
            self.stdout.write(self.style.SUCCESS('Depth scan complete.'))

        if run_all or options['purge']:
            self.stdout.write('Purging old decay logs...')
            purge_old_decay_logs()
            self.stdout.write(self.style.SUCCESS('Decay log purge complete.'))
