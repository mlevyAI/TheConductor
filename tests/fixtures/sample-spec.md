# TaskFlow — Project Spec

## Overview
A task management SaaS for remote teams. Helps distributed teams track work,
assign responsibilities, and hit deadlines without the overhead of heavyweight
project-management tools.

## Stack
Next.js 14, Supabase (PostgreSQL), Tailwind CSS, TypeScript

## Language
TypeScript (primary)

## Text Direction
ltr

## Authentication
JWT with Supabase Auth

## Current Phase
Phase 1: Core task management

### In scope
- User registration and login
- Create/edit/delete tasks
- Assign tasks to team members
- Basic dashboard with task overview

### Out of scope
- Team collaboration features (comments, @mentions)
- Mobile app
- Third-party integrations (Slack, Jira)
- Advanced reporting

## Data Model

Tables: users, tasks, projects

### users
| Column     | Type      | Notes                    |
|------------|-----------|--------------------------|
| id         | uuid      | primary key              |
| email      | text      | unique, not null         |
| created_at | timestamp | default now()            |

### projects
| Column      | Type      | Notes                    |
|-------------|-----------|--------------------------|
| id          | uuid      | primary key              |
| name        | text      | not null                 |
| owner_id    | uuid      | fk → users.id            |
| created_at  | timestamp | default now()            |

### tasks
| Column      | Type      | Notes                         |
|-------------|-----------|-------------------------------|
| id          | uuid      | primary key                   |
| title       | text      | not null                      |
| project_id  | uuid      | fk → projects.id              |
| assignee_id | uuid      | fk → users.id, nullable       |
| status      | text      | todo / in_progress / done     |
| due_date    | date      | nullable                      |
| created_at  | timestamp | default now()                 |

## Domain
B2B SaaS — team productivity
