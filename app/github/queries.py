DEFAULT_BRANCH_QUERY = """
query DefaultBranch($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      name
    }
  }
}
"""

PR_WITH_REVIEWS = """
query PullRequestsWithReviews(
  $owner: String!
  $name: String!
  $after: String
) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      name
    }
    pullRequests(
      first: 100
      after: $after
      orderBy: { field: CREATED_AT, direction: DESC }
      states: [OPEN, CLOSED, MERGED]
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        number
        state
        createdAt
        mergedAt
        closedAt
        additions
        deletions
        author {
          login
        }
        reviews(first: 100) {
          pageInfo {
            hasNextPage
          }
          nodes {
            databaseId
            state
            submittedAt
            author {
              login
            }
          }
        }
      }
    }
  }
  rateLimit {
    remaining
    resetAt
  }
}
"""

COMMITS_ON_DEFAULT_BRANCH = """
query CommitsOnDefault(
  $owner: String!
  $name: String!
  $branch: String!
  $since: GitTimestamp!
  $until: GitTimestamp!
  $after: String
) {
  repository(owner: $owner, name: $name) {
    ref(qualifiedName: $branch) {
      target {
        ... on Commit {
          history(first: 100, after: $after, since: $since, until: $until) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              oid
              additions
              deletions
              committedDate
              author {
                user {
                  login
                }
                name
              }
            }
          }
        }
      }
    }
  }
  rateLimit {
    remaining
    resetAt
  }
}
"""
