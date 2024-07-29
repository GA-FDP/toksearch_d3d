/*
Copyright 2024 General Atomics

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "sqlite_index.h"

#define SHOTS_PER_INDEX 100
#define MAX_PATH_LENGTH 4096

// The number of databases that can be cached
// The number of indices is the max number of shots divided by SHOTS_PER_INDEX
// So, this will be valid until exceeds 1,000,000 (we're around 200,000 now)
#define MAX_DB_COUNT 10000

typedef enum {
    SQLITE_INDEX_SUCCESS,
    SQLITE_INDEX_DB_OPEN_ERROR,
    SQLITE_INDEX_PREPARE_ERROR,
    SQLITE_INDEX_NO_RESULT_FOUND,
    SQLITE_INDEX_ENV_VAR_NOT_SET
} IndexErrorCodes;

static sqlite3* openDatabase(int shot);
static sqlite3* getDb(int shot);
static void setDb(int shot, sqlite3 *db);
static int calculateIndex(int shot);

static sqlite3 *db_cache[MAX_DB_COUNT];

static sqlite3* getDb(int shot) {
    int index = calculateIndex(shot);
    return db_cache[index];
}

static void setDb(int shot, sqlite3 *db) {
    int index = calculateIndex(shot);
    db_cache[index] = db;
}

static int calculateIndex(int shot) {
    return shot / SHOTS_PER_INDEX;
}

static sqlite3* openDatabase(int shot) {

    // First check if the db has been cached in the global hash table
    // If it has, return the db

    sqlite3 *cached_db = getDb(shot);
    if (cached_db) {
        return cached_db;
    }

    const char* dbDirectory = getenv("TOKSEARCH_INDEX_DIR");
    if (!dbDirectory) {
        fprintf(stderr, "Environment variable TOKSEARCH_INDEX_DIR not set.\n");
        return NULL;
    }

    char dbName[MAX_PATH_LENGTH];
    snprintf(dbName, sizeof(dbName), "%s/%d.db", dbDirectory, calculateIndex(shot));

    sqlite3* db;
    int rc = sqlite3_open_v2(dbName, &db, SQLITE_OPEN_READONLY, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot open database: %s\n", sqlite3_errmsg(db));
        sqlite3_close(db);
        return NULL;
    }

    setDb(shot, db);
    return db;
}

char *get_shot_file_path(const char* pointname, int shot) {

    char *result = NULL;

     sqlite3* db = openDatabase(shot);

    if (db == NULL) {
        return NULL;
    }


    sqlite3_stmt* stmt;
    const char* query = "SELECT dir || '/' || shot || ext FROM fulldir_map WHERE pointname = upper(trim(?)) AND shot = ?";
    int rc = sqlite3_prepare_v2(db, query, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Failed to prepare statement: %s\n", sqlite3_errmsg(db));
        return NULL;
    }

    sqlite3_bind_text(stmt, 1, pointname, -1, SQLITE_STATIC);
    sqlite3_bind_int(stmt, 2, shot);

    if (sqlite3_step(stmt) == SQLITE_ROW) {
        const char* path = (const char*)sqlite3_column_text(stmt, 0);
        size_t path_len = strlen(path);

        result = malloc(path_len + 1);
        strcpy(result, path);

    } else {
        result = NULL;
    }

    sqlite3_finalize(stmt);
    return result;
}
