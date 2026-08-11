# Orlando Land Detector - Interactive Dashboard

## Overview

A real-time, interactive web-based dashboard for analyzing real estate opportunities in the Orlando, Florida market. Built with HTML5, JavaScript, and Leaflet for mapping.

## Features

### 📊 Summary Section
- **Total Opportunities**: Count of all analyzed properties
- **Viable Count**: Properties ready for execution (Viável = green)
- **Radar Count**: Properties under analysis (Radar = yellow)
- **Rejected Count**: Properties that failed analysis (Reprovada = red)
- **Best Margin**: Highest margin opportunity
- **New in 24h**: Properties added in the last 24 hours
- **Last Capture**: Date and time of the latest data

### 🗺️ Interactive Map
- Color-coded pins by status:
  - **Green**: Viable - Ready for development
  - **Yellow**: Radar - Pending analysis or confirmation
  - **Red**: Rejected - Eliminated from consideration
- Click pins for detailed property information
- Auto-centered on Orlando area with zoom controls

### 📈 Radar Tab
- Sortable table of radar-stage opportunities
- Quick sort by:
  - Margin (highest first)
  - Profit (highest first)
  - Date (most recent first)
- Columns: Date, Address, ZIP, Market, Price, ARV, Profit, Margin, Recommendation

### 📊 Regional Growth Signals Chart
- Bar chart showing opportunity distribution by region
- Breakdown by status (Viable, Radar, Rejected)
- Regional analysis and trends
- Summary statistics for each market area

### 🔗 Comparison View
- Scatter plot: Margin (X) vs Profit (Y)
- Top 10 opportunities plotted
- Interactive tooltips showing property details
- Top 5 viable opportunities by profit

### 📋 Data Table
- Complete filterable dataset
- Filters:
  - Status (Viable/Radar/Rejected)
  - Address search
  - ZIP code search
  - Minimum margin percentage
- Sortable columns
- All key metrics displayed

## Data Structure

### Expected JSON Format

```json
{
  "opportunities": [
    {
      "id": "ORL-001",
      "address": "123 Main St, Orlando, FL",
      "zip_code": "32801",
      "lat": "28.5421",
      "lng": "-81.3723",
      "county": "Orange County",
      "market_priority": "Downtown",
      "tier": "A",
      "land_price": 500000,
      "arv": 850000,
      "profit": 250000,
      "margin": 0.35,
      "gross_acres": 0.75,
      "estimated_net_developable_acres": 0.65,
      "cadastral_use": "Vacant Land",
      "cadastral_use_source": "County Records",
      "zoning": "Commercial",
      "entitlement_stage": "Entitled",
      "future_land_use": "Commercial Development",
      "is_viable": "yes",
      "review_status": "viavel",
      "due_diligence_recommendation": "Proceed - Strong ROI",
      "due_diligence_completion_pct": 95,
      "pending_confirmations": "",
      "risk_flags": "",
      "reasons": "",
      "found_at": "2026-08-11T14:30:00Z",
      "url": "https://example.com/property/1"
    }
  ]
}
```

### Status Values

**is_viable**: "yes" or "no" (or empty)

**review_status**:
- `viavel` - Viable, ready for execution
- `radar_*` - Under radar analysis (e.g., `radar_zone_change`, `radar_analysis_manual`)
- `reprovada` - Rejected
- Empty or other values default to rejected

## Deployment to GitHub Pages

### Setup

1. Ensure GitHub Pages is enabled in repository settings
2. Configure to deploy from `gh-pages` branch

### Auto-Deployment

Files are automatically deployed to GitHub Pages:
- `index.html` - Main dashboard
- `data.json` - Opportunity data

### Manual Update Process

```bash
# 1. Update opportunities.csv and evaluations.csv
# 2. Run analysis to generate data.json
# 3. Commit and push to main branch
# 4. System automatically syncs to gh-pages
```

### Live URL

https://gchohfi.github.io/Zillow/

## Performance Metrics

### Load Times
- Page load: < 2 seconds (with sample data)
- Map rendering: < 500ms
- Chart rendering: < 300ms
- Filter/sort operations: < 100ms

### Browser Support
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## API & Data Dependencies

### External Libraries
- **Chart.js** 4.4.1 - Chart rendering
- **Leaflet** 1.9.4 - Interactive mapping
- **OpenStreetMap Tiles** - Map background

### Data Source
- `data.json` - Local JSON file with all opportunity records

## Customization

### Color Scheme
- Viable: `#28a745` (green)
- Radar: `#ffc107` (yellow)
- Rejected: `#dc3545` (red)
- Primary: `#667eea` (purple)

### Modify in CSS section:
```css
.status-viavel { background: #28a745; }
.status-radar { background: #ffc107; }
.status-reprovada { background: #dc3545; }
```

## Troubleshooting

### Empty Dashboard
- Check `data.json` exists and is valid JSON
- Verify browser console for errors
- Check network tab for data.json load

### Map Not Showing
- Ensure lat/lng fields are present and valid numbers
- Check Leaflet CDN is accessible
- Verify coordinate format (decimal degrees)

### Charts Not Rendering
- Verify Chart.js CDN is accessible
- Check data has required fields (margin, profit, region)
- Ensure canvas elements are present in HTML

## Future Enhancements

- [ ] Real-time data updates with WebSocket
- [ ] Export to CSV/PDF
- [ ] Advanced filtering (date range, price range)
- [ ] Property image gallery
- [ ] Market heat map
- [ ] Comparative market analysis
- [ ] Risk scoring visualization
- [ ] Time-series trend analysis

## File Structure

```
Zillow/
├── index.html          # Main dashboard (deployed to gh-pages)
├── data.json           # Opportunity data
├── dashboard-README.md # This file
├── src/                # Python analysis scripts
└── .github/workflows/  # CI/CD automation
```

## Support

For issues or feature requests, create an issue in the repository.

---

**Dashboard Version**: 1.0.0  
**Last Updated**: 2026-08-11
