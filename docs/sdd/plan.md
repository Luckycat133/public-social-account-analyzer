# SDD Implementation Plan

## Goal
Implement a reliable, compliant, multi-platform public social account analyzer following the Agent Skill specification.

## Components
1. **Collectors**: Bilibili, Douyin, Weibo platform collectors in `skill/scripts/collectors/`.
2. **Normalizer**: Normalize heterogeneous raw data into `normalized-posts.csv`.
3. **Analyzer**: Compute statistical metrics (medians, percentiles) and strategy taxonomy.
4. **Renderer**: Render markdown reports and HTML dashboards.
