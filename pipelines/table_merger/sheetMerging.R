# merge_v1_v2_from_xlsx.R
# Lightweight merge tool:
# - Reads a 3-sheet XLSX: mapping, V2, V1
# - Produces a merged dataset with canonical columns first, then prefixed leftovers

suppressPackageStartupMessages({
  library(readxl)
  library(dplyr)
  library(stringr)
  library(openxlsx)
})

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0) b else a

merge_from_xlsx <- function(
  xlsx_path,
  out_xlsx_path = "merged.xlsx",
  map_sheet = 1,
  v2_sheet = 2,
  v1_sheet = 3,
  v2_prefix = "V2_",
  v1_prefix = "V1_",
  v1_notpresent_prefix = "V1_NotPresent_",
  v2_notpresent_prefix = "V2_NotPresent_",
  add_wave_col = TRUE,
  wave_col = "wave",
  strict = FALSE
) {
  # ---- Read inputs ----
  map_raw <- readxl::read_excel(
    xlsx_path,
    sheet = map_sheet,
    col_names = TRUE,
    .name_repair = "unique"
  )

  v2 <- readxl::read_excel(
    xlsx_path,
    sheet = v2_sheet,
    col_names = TRUE,
    col_types = "text",
    .name_repair = "unique"
  )

  v1 <- readxl::read_excel(
    xlsx_path,
    sheet = v1_sheet,
    col_names = TRUE,
    col_types = "text",
    .name_repair = "unique"
  )

  # Validate expected columns
  required_cols <- c("V1_old_cols", "V2_new_cols")
  missing_cols <- setdiff(required_cols, names(map_raw))
  if (length(missing_cols) > 0) {
    stop(
      "Mapping sheet is missing required columns: ",
      paste(missing_cols, collapse = ", ")
    )
  }

  map <- map_raw %>%
    transmute(
      v1_name = as.character(V1_old_cols),
      v2_name = as.character(V2_new_cols)
    ) %>%
    mutate(
      v2_name = stringr::str_squish(v2_name),
      v1_name = stringr::str_squish(v1_name),
      v1_name = dplyr::na_if(v1_name, ""),
      v2_name = dplyr::na_if(v2_name, "")
    ) %>%
    filter(!is.na(v2_name)) %>%
    distinct(v2_name, .keep_all = TRUE)

  if (nrow(map) == 0) stop("Mapping sheet has no usable v2_name entries in column 1.")

  canonical <- map$v2_name

  # ---- Validate mapping against source columns (optional strict mode) ----
  missing_in_v2 <- setdiff(canonical, names(v2))
  if (strict && length(missing_in_v2) > 0) {
    stop("Strict mode: these v2_name columns are not present in V2: ",
         paste(missing_in_v2, collapse = ", "))
  }

  v1_mapped_names <- map$v1_name[!is.na(map$v1_name)]
  missing_in_v1 <- setdiff(v1_mapped_names, names(v1))
  if (strict && length(missing_in_v1) > 0) {
    stop("Strict mode: these v1_name columns are not present in V1: ",
         paste(missing_in_v1, collapse = ", "))
  }

  # ---- Build canonical columns for V2 ----
  # Create any missing canonical columns as NA (if not strict)
  for (nm in missing_in_v2) {
    v2[[nm]] <- rep(NA_character_, nrow(v2))
  }

  v2_canon <- v2 %>%
    select(any_of(canonical))

  # ---- Build canonical columns for V1 by renaming mapped v1_name -> v2_name ----
  # Start with empty canonical frame, then fill from v1 where mapping exists.
  n1 <- nrow(v1)
  v1_canon <- as_tibble(setNames(
    replicate(length(canonical), rep(NA_character_, n1), simplify = FALSE),
    canonical
  ))

  # Fill columns where mapping exists and v1 has the column
  for (i in seq_len(nrow(map))) {
    tgt <- map$v2_name[i]
    src <- map$v1_name[i]
    if (!is.na(src) && src %in% names(v1)) {
      v1_canon[[tgt]] <- v1[[src]]
    }
  }

  # ---- NotPresent renaming for canonical columns ----

  # v1_present: mapped source exists in V1 (non-NA mapping and column exists)
  v1_intended <- !is.na(map$v1_name) & map$v1_name != ""

  v1_present <- v1_intended & (map$v1_name %in% names(v1))
  v2_present <- canonical %in% names(v2)

  v1_notpresent_flag <- v2_present & v1_intended & !v1_present
  v2_notpresent_flag <- v1_present & !v2_present

    
  # Determine renamed canonical column names
  canonical_renamed <- canonical

  # If present in V2 but NOT present in V1 -> prefix with V1_NotPresent_
  canonical_renamed[v1_notpresent_flag] <-
    paste0(v1_notpresent_prefix, canonical[v1_notpresent_flag])


  # If present in V1 but NOT present in V2 -> prefix with V2_NotPresent_
  canonical_renamed[v2_notpresent_flag] <-
    paste0(v2_notpresent_prefix, canonical[v2_notpresent_flag])

  # Apply renames consistently to both V1 and V2 canonical blocks
  rename_map <- setNames(canonical, canonical_renamed)

  v2_canon <- v2_canon %>% rename(!!!rename_map)
  v1_canon <- v1_canon %>% rename(!!!rename_map)


  # ---- Identify "other" columns not in mapping ----
  # V2 other = columns in V2 not in canonical
  v2_other_names <- setdiff(names(v2), canonical)
  # V1 other = columns in V1 not used as a v1_name mapping target
  v1_used_sources <- unique(v1_mapped_names)
  v1_other_names <- setdiff(names(v1), v1_used_sources)

  v2_other <- if (length(v2_other_names) == 0) {
    tibble(.rows = nrow(v2))
  } else {
    v2 %>%
      select(any_of(v2_other_names)) %>%
      rename_with(~ paste0(v2_prefix, .x))
  }

  v1_other <- if (length(v1_other_names) == 0) {
    tibble(.rows = nrow(v1))
  } else {
    v1 %>%
      select(any_of(v1_other_names)) %>%
      rename_with(~ paste0(v1_prefix, .x))
  }

  # ---- Assemble aligned datasets ----
  v2_out <- bind_cols(v2_canon, v2_other)
  v1_out <- bind_cols(v1_canon, v1_other)

  if (add_wave_col) {
    v1_out <- v1_out %>% mutate("{wave_col}" := "V1", .before = 1)
    v2_out <- v2_out %>% mutate("{wave_col}" := "V2", .before = 1)
  }

  # ---- Coerce shared columns to character before bind_rows ----
  common_cols <- intersect(names(v1_out), names(v2_out))

  v1_out <- v1_out %>% mutate(across(everything(), as.character))
  v2_out <- v2_out %>% mutate(across(everything(), as.character))


  merged <- bind_rows(v1_out, v2_out)

  # ---- Ensure final column order: wave (optional), NotPresent canonical first, then remaining canonical, then others ----
  is_notpresent <- v1_notpresent_flag | v2_notpresent_flag


  notpresent_cols <- canonical_renamed[is_notpresent]
  regular_canonical_cols <- canonical_renamed[!is_notpresent]


  base_cols <- c(notpresent_cols, regular_canonical_cols)
  if (add_wave_col) base_cols <- c(wave_col, base_cols)

  merged <- merged %>%
    select(any_of(base_cols), everything())

  # ---- Write outputs ----
  wb <- createWorkbook()
  addWorksheet(wb, "merged")
  writeDataTable(wb, "merged", merged)

  # Optional: write diagnostics for transparency
  addWorksheet(wb, "diagnostics")
  diag <- tibble(
    canonical_cols = canonical,
    output_col = canonical_renamed,
    v2_present = v2_present,
    v1_source = map$v1_name %||% NA_character_,
    v1_present = v1_present
  )
  writeDataTable(wb, "diagnostics", diag)

  saveWorkbook(wb, out_xlsx_path, overwrite = TRUE)

  invisible(list(
    merged = merged,
    diagnostics = diag,
    out_xlsx_path = out_xlsx_path
  ))
}

result <- tryCatch(
  merge_from_xlsx("d:\\env\\Wincross\\3783_Map.xlsx", out_xlsx_path = "merged.xlsx", strict = FALSE),
  error = function(e) {
    message("merge_from_xlsx() failed: ", conditionMessage(e))
    NULL
  }
)

if (!is.null(result)) {
  View(result$diagnostics)
}