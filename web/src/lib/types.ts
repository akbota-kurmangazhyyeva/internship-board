// Mirrors backend/app/schemas.py (the API contract). null means "Unknown": never show a guess (FR-07, NFR-11).

export type Level = "intern" | "junior" | "mid" | "senior";
export type WorkFormat = "remote" | "hybrid" | "onsite";
export type Language = "kk" | "ru" | "en";
export type EducationLevel = "college" | "bachelor" | "master" | "phd";
export type Sort = "relevance" | "newest" | "deadline" | "fit";

export interface Salary {
  min?: number | null;
  max?: number | null;
  currency?: string | null;
  period?: string | null;
  unpaid?: boolean;
  gross_net?: string | null;
  text?: string | null;
}

export interface Reason {
  code: string;
  text: string;
  polarity: number;
  params: Record<string, unknown>;
}

export interface Fit {
  score: number;
  eligible: boolean;
  summary: string;
  reasons: Reason[];
  violations: Reason[];
}

export interface VacancyCard {
  id: number;
  title: string;
  employer: string | null;
  status: string;
  is_internship: boolean | null;
  level: Level | null;
  work_format: WorkFormat | null;
  cities: string[];
  skills: string[];
  languages: string[];
  deadline: string | null;
  salary: Salary | null;
  published_at: string | null;
  last_checked_at: string;
  sources: string[];
  fit: Fit | null;
  is_saved: boolean | null;
}

export interface FieldMeta {
  status: "ok" | "low_confidence" | "conflict" | "missing" | string;
  confidence: number | null;
  method: string | null;
  evidence: string | null;
}

export interface SourceLink {
  source: string;
  source_key: string;
  url: string;
  first_seen_at: string;
  last_checked_at: string;
  live: boolean;
}

export interface VacancyDetail extends VacancyCard {
  description: string;
  posting_language: string | null;
  eligibility: { min_year?: number | null; max_year?: number | null } | null;
  apply_url: string | null;
  fields: Record<string, FieldMeta>;
  source_links: SourceLink[];
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface FeedPage extends Page<VacancyCard> {
  relaxed: boolean;
  profile_complete: boolean;
  hint: string | null;
}

export interface Profile {
  education_level: EducationLevel | null;
  year_of_study: number | null;
  expected_graduation_year: number | null;
  field_of_study: string | null;
  skills: string[];
  preferred_cities: string[];
  work_formats: WorkFormat[];
  target_levels: Level[];
  languages: Language[];
  interests: string[];
  open_to_relocation: boolean;
  updated_at?: string | null;
}

export interface User {
  id: number;
  email: string;
  role: string;
  tracking_consent: boolean;
}

export interface SavedItem {
  vacancy: VacancyCard;
  saved_at: string;
  remind: boolean;
}

export interface FiltersMeta {
  cities: string[];
  skills: string[];
  levels: string[];
  work_formats: string[];
  languages: string[];
  sorts: string[];
}

export interface VacancyFilters {
  q?: string;
  skill?: string[];
  city?: string[];
  work_format?: string[];
  level?: string[];
  language?: string[];
  deadline_from?: string;
  deadline_to?: string;
  internship_only?: boolean;
  sort?: Sort;
}
