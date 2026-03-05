"""
Trigger GEO/SEO/CRO page analysis for a site's pages (e.g. for fnbcoweta.com).

Usage:
  python manage.py run_page_analyses fnbcoweta.com
  python manage.py run_page_analyses fnbcoweta.com --limit 5
  python manage.py run_page_analyses 123  # by site id
"""
from urllib.parse import urlparse

from django.core.management.base import BaseCommand
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from seo.page_analysis_views import analyze_page
from sites.models import Site


class Command(BaseCommand):
    help = "Run page analysis (GEO/SEO/CRO) for up to N pages of a site (by URL or site id)."

    def add_arguments(self, parser):
        parser.add_argument(
            "site",
            type=str,
            help="Site identifier: domain (e.g. fnbcoweta.com) or numeric site id",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Max number of pages to analyze (default: 5)",
        )

    def handle(self, site_arg, **options):
        limit = options["limit"]

        if site_arg.isdigit():
            site = Site.objects.filter(id=int(site_arg)).first()
        else:
            domain = site_arg.strip().lower()
            if "http" not in domain:
                domain = f"https://{domain}/"
            site = Site.objects.filter(url__icontains=domain.replace("https://", "").replace("http://", "").split("/")[0]).first()

        if not site:
            self.stderr.write(self.style.ERROR(f"Site not found: {site_arg}"))
            return

        pages = list(
            site.pages.filter(status="publish", is_noindex=False).order_by("-is_money_page", "-is_homepage", "url")[:limit]
        )
        if not pages:
            self.stderr.write(self.style.WARNING(f"No published pages found for site id={site.id} ({site.name}). Sync pages first."))
            return

        self.stdout.write(f"Site: {site.name} (id={site.id}) — analyzing {len(pages)} page(s) as user {site.user.email}")

        factory = APIRequestFactory()
        for page in pages:
            path = urlparse(page.url).path or "/"
            req = factory.post(
                f"/api/v1/sites/{site.id}/pages/analyze/",
                {"page_url": path},
                format="json",
            )
            req.user = site.user
            drf_request = Request(req)
            response = analyze_page(drf_request, site.id)
            status_code = response.status_code
            if status_code in (200, 201):
                self.stdout.write(self.style.SUCCESS(f"  [{status_code}] {path}"))
            else:
                self.stdout.write(self.style.ERROR(f"  [{status_code}] {path} — {getattr(response, 'data', response)}"))

        self.stdout.write(self.style.SUCCESS(f"Done. Check dashboard or GET /api/v1/sites/{site.id}/pages/analysis/ for results."))
