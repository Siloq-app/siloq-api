# CLAUDE.md — Siloq API Development Rules

## Architecture Principles

The **Site Entity Profile** is the single source of truth for all business data used in schema generation. Every page's schema references this profile. When business data changes (hours, services, reviews), schema updates everywhere automatically.

**Entity extraction feeds schema directly:**
- `brand` / `brand_line` entities → Product schema `brand` property
- `service_type` entities → Service schema `serviceType`, `areaServed`
- `location` entities → LocalBusiness schema `areaServed`, `address`
- `product_name` entities → Product schema `name`, `sku`, `offers`
- FAQ content from GEO recommendations → FAQPage schema
- Review data from GBP → AggregateRating + Review schema

## Schema Generation Rules

Schema types are determined **automatically** by page type — users never manually select schema.

| Page Type | Schema Types |
|-----------|-------------|
| Homepage | Organization/LocalBusiness, WebSite (SearchAction), sameAs social profiles |
| Service pages | Service, FAQPage (from GEO Q&As), BreadcrumbList |
| Product pages | Product, AggregateRating, BreadcrumbList |
| Blog posts | Article, FAQPage, HowTo, BreadcrumbList |
| Location pages | LocalBusiness, Service, GeoCircle |
| About page | Organization, Person (team members) |
| Contact page | ContactPoint, PostalAddress |
| Reviews page | AggregateRating, Review items from GBP |

Schema must be validated against Google Rich Results requirements before pushing to WordPress.

**Plugin conflict rule:** Always detect existing SEO plugin schema (AIOSEO, Yoast, RankMath). Never duplicate Organization or LocalBusiness schema. Either enhance existing schema with missing properties or replace it — never stack two of the same type.

## ABSOLUTE RULE — NO FAKE TESTIMONIALS OR REVIEWS

**NEVER generate fabricated customer quotes, fake names, or invented social proof.**

This is a legal liability for customers. Example of what is FORBIDDEN:
> "The Remodel Co. transformed our bathroom beautifully! — Jane D."

If real GBP review data is available in the Site Entity Profile → use actual quotes with real reviewer names.

If GBP is not connected → CRO recommendation must say:
> "Connect your Google Business Profile in Settings to pull real customer reviews for this section."

No exceptions.

## Migration Numbering

Always check `seo/migrations/` for the highest migration number before creating a new one. Never use duplicate numbers. Current latest: `0017_pageanalysis_generated_schema`.

## Pre-Merge Checklist

Before any PR is merged to `release/v2.0`:
1. Check for duplicate migration numbers in `seo/migrations/`
2. Verify no Python syntax errors in changed files
3. Confirm all new model fields have corresponding migrations
4. Check `sites/urls.py` that imported view functions actually exist
