export type TaxonomyBadge = 'OBSERVED' | 'DERIVED' | 'SCENARIO' | 'UNAVAILABLE';
export type RouteMode = 'fastest' | 'balanced' | 'safest';
export type ViewMode = 'map2d' | 'terrain3d' | 'hud';
export type BudgetType = 'o2' | 'time';
export type CrewMode = 'buddy' | 'solo';

export interface ConstantItem {
  value: number;
  range?: [number, number];
  uncertainty?: number;
  formula?: string;
  units: string;
  badge: TaxonomyBadge;
  source_title: string;
  source_url: string;
  note: string;
}

export interface ConstantsFile {
  schema_version: string;
  ops_bbox_lonlat: [number, number, number, number];
  crs: {
    name: string;
    proj4: string;
    radius_m: number;
    deg_to_m_lat: number;
    ref_lat_deg: number;
    cos_ref_lat: number;
  };
  constants: Record<string, ConstantItem>;
}

export interface LayerMeta {
  id: string;
  title: string;
  data_kind: string;
  badge: TaxonomyBadge;
  default_visible: boolean;
  default_opacity: number;
  native_resolution: string;
  image_url: string;
  pixelated: boolean;
  source_product: string;
  source_url: string;
  acquisition_date: string;
  license: string;
  credit: string;
  limitations: string;
}

export interface LayersManifest {
  ops_bbox_lonlat: [number, number, number, number];
  grid_shape: [number, number];
  grid_resolution_m: number;
  constants_hash: string;
  layers: LayerMeta[];
}

export interface TargetSite {
  id: string;
  name: string;
  category: string;
  lon: number;
  lat: number;
  elev_m: number;
  slope_max_deg: number;
  los_visible: boolean;
  sky_view_factor: number;
  badge: TaxonomyBadge;
  geologic_unit: string;
  evidence: string;
  source_url: string;
  science_priority: number;
}

export interface HabitatSite {
  id: string;
  name: string;
  lon: number;
  lat: number;
  elev_m: number;
  badge: TaxonomyBadge;
  description: string;
}

export interface TargetsFile {
  habitat: HabitatSite;
  targets: TargetSite[];
}

export interface WaypointProfile {
  idx: number;
  row: number;
  col: number;
  lon: number;
  lat: number;
  elev_m: number;
  cum_dist_m: number;
  seg_slope_mean_deg: number;
  seg_slope_max_deg: number;
  surf_eta: number;
  los: number;
  used_time_s: number;
  back_time_s: number;
  used_o2_l_base: number;
  back_o2_l_base: number;
  dominant_cost_reason: string;
}

export interface RouteBundle {
  goal_id: string;
  goal_name: string;
  mode: RouteMode;
  mode_caption: string;
  alpha: number;
  constants_hash: string;
  reference_norms: {
    t_ref_s: number;
    r_ref_score: number;
  };
  summary: {
    distance_m: number;
    outbound_time_s: number;
    return_time_from_goal_s: number;
    outbound_o2_liters_base: number;
    return_o2_from_goal_liters_base: number;
    default_kappa: number;
    max_slope_crossed_deg: number;
    mean_slope_deg: number;
    hard_limit_deg: number;
    los_coverage_pct: number;
    hazard_breakdown: {
      slope_penalty: number;
      sand_ti_penalty: number;
      data_gap_penalty: number;
      los_penalty: number;
      total_hazard_score: number;
    };
  };
  geometry: {
    type: 'LineString';
    coordinates: [number, number, number][];
  };
  waypoints_profile: WaypointProfile[];
}

export interface CuriosityPhotoPin {
  id: string;
  sol: number | string;
  instrument: string;
  title: string;
  caption: string;
  date_taken_utc: string;
  local_image: string;
  source_url: string;
  credit: string;
  lon: number;
  lat: number;
  region_label: string;
  badge: TaxonomyBadge;
  location_accuracy: string;
}

export interface EnvironmentContext {
  radiation: {
    badge: string;
    gcr_baseline_msv_day: number;
    gcr_uncertainty_msv_day: number;
    source_citation: string;
    spatial_map_status: string;
    spatial_note: string;
    svf_summary: { min: number; mean: number; max: number };
    sep_scenarios: {
      id: string;
      label: string;
      extra_dose_msv: number;
      multiplier: number;
      source: string;
    }[];
  };
  weather_rems: {
    badge: string;
    pressure_range_pa: [number, number];
    air_temp_c_range: [number, number];
    ground_temp_c_range: [number, number];
    wind_typical_mps: [number, number];
    source_citation: string;
    mcd_note: string;
    solar_curve: { local_solar_hour: number; sun_elevation_deg: number }[];
  };
  curiosity_photos: CuriosityPhotoPin[];
}

export interface TerrainMesh {
  rows: number;
  cols: number;
  bbox: [number, number, number, number];
  dx_m: number;
  dy_m: number;
  elev_min_m: number;
  elev_max_m: number;
  elev: number[][];
}

export interface MissionParams {
  goalId: string;
  mode: RouteMode;
  crewMode: CrewMode;
  loadKg: number;
  kappa: number;
  budgetType: BudgetType;
  o2BudgetLiters: number;
  timeBudgetHours: number;
  reserveFraction: number;
}
