"""TaskFlow: a task-management API (Node.js, JavaScript then TypeScript),
January to May 2026.

The story RepoMind should find:
  - a layered Express app: controllers -> services -> repositories
  - decisions: the move from JavaScript to TypeScript (renames + tsconfig),
    callbacks replaced by async/await classes, Postgres via `pg` then
    replaced by Prisma, zod validation, an `@app/*` path alias with barrel
    exports, a domain event bus, Jest and CI
  - drift: an archive hotfix in the task controller writes through Prisma
    (later moved into the service), and the project page's open-task count
    calls the task repository from the project controller through an
    injected, alias-imported TaskRepository (still there at HEAD)
"""
from datetime import datetime

ANA = ("Ana Souza", "ana@taskflow.example")
KENJI = ("Kenji Watanabe", "kenji@taskflow.example")
LEILA = ("Leila Haddad", "leila@taskflow.example")

# ------------------------------------------------------------------ JavaScript, callbacks

PKG_V1 = '''{
  "name": "taskflow",
  "version": "0.1.0",
  "private": true,
  "main": "src/server.js",
  "scripts": { "start": "node src/server.js" },
  "dependencies": {
    "express": "^4.18.2"
  }
}
'''

SERVER_JS = '''const app = require('./app');

const port = process.env.PORT || 3000;
app.listen(port, () => console.log(`TaskFlow listening on ${port}`));
'''

APP_JS_V1 = '''const express = require('express');
const taskController = require('./controllers/task.controller');

const app = express();
app.use(express.json());

app.get('/tasks', taskController.list);
app.post('/tasks', taskController.create);
app.post('/tasks/:id/complete', taskController.complete);

module.exports = app;
'''

TASK_MODEL_JS = '''function createTask({ title, projectId, dueDate }) {
  return { id: null, title: title.trim(), projectId, dueDate: dueDate || null, status: 'open', createdAt: new Date() };
}

module.exports = { createTask };
'''

TASK_REPO_JS = '''const tasks = new Map();
let nextId = 1;

function findAll(callback) {
  setImmediate(() => callback(null, Array.from(tasks.values())));
}

function findById(id, callback) {
  setImmediate(() => callback(null, tasks.get(Number(id)) || null));
}

function save(task, callback) {
  if (!task.id) task.id = nextId++;
  tasks.set(task.id, task);
  setImmediate(() => callback(null, task));
}

module.exports = { findAll, findById, save };
'''

TASK_SERVICE_JS = '''const taskRepository = require('../repositories/task.repository');
const { createTask } = require('../models/task.model');

function listTasks(callback) {
  taskRepository.findAll(callback);
}

function addTask(input, callback) {
  if (!input || !input.title) return callback(new Error('title is required'));
  taskRepository.save(createTask(input), callback);
}

function completeTask(id, callback) {
  taskRepository.findById(id, (err, task) => {
    if (err) return callback(err);
    if (!task) return callback(new Error('task not found'));
    task.status = 'done';
    taskRepository.save(task, callback);
  });
}

module.exports = { listTasks, addTask, completeTask };
'''

TASK_CONTROLLER_JS = '''const taskService = require('../services/task.service');

function list(req, res) {
  taskService.listTasks((err, tasks) => (err ? res.status(500).json({ error: err.message }) : res.json(tasks)));
}

function create(req, res) {
  taskService.addTask(req.body, (err, task) => (err ? res.status(400).json({ error: err.message }) : res.status(201).json(task)));
}

function complete(req, res) {
  taskService.completeTask(req.params.id, (err, task) => (err ? res.status(404).json({ error: err.message }) : res.json(task)));
}

module.exports = { list, create, complete };
'''

PROJECT_MODEL_JS = '''function createProject({ name, ownerId }) {
  return { id: null, name: name.trim(), ownerId, archived: false };
}

module.exports = { createProject };
'''

PROJECT_REPO_JS = '''const projects = new Map();
let nextId = 1;

function findAll(callback) {
  setImmediate(() => callback(null, Array.from(projects.values()).filter((p) => !p.archived)));
}

function findById(id, callback) {
  setImmediate(() => callback(null, projects.get(Number(id)) || null));
}

function save(project, callback) {
  if (!project.id) project.id = nextId++;
  projects.set(project.id, project);
  setImmediate(() => callback(null, project));
}

module.exports = { findAll, findById, save };
'''

PROJECT_SERVICE_JS = '''const projectRepository = require('../repositories/project.repository');
const { createProject } = require('../models/project.model');

function listProjects(callback) {
  projectRepository.findAll(callback);
}

function addProject(input, callback) {
  if (!input || !input.name) return callback(new Error('name is required'));
  projectRepository.save(createProject(input), callback);
}

module.exports = { listProjects, addProject };
'''

PROJECT_CONTROLLER_JS = '''const projectService = require('../services/project.service');

function list(req, res) {
  projectService.listProjects((err, projects) => (err ? res.status(500).json({ error: err.message }) : res.json(projects)));
}

function create(req, res) {
  projectService.addProject(req.body, (err, project) => (err ? res.status(400).json({ error: err.message }) : res.status(201).json(project)));
}

module.exports = { list, create };
'''

APP_JS_V2 = '''const express = require('express');
const taskController = require('./controllers/task.controller');
const projectController = require('./controllers/project.controller');

const app = express();
app.use(express.json());

app.get('/tasks', taskController.list);
app.post('/tasks', taskController.create);
app.post('/tasks/:id/complete', taskController.complete);
app.get('/projects', projectController.list);
app.post('/projects', projectController.create);

module.exports = app;
'''

# ------------------------------------------------------------------ TypeScript

PKG_TS = '''{
  "name": "taskflow",
  "version": "0.2.0",
  "private": true,
  "main": "dist/server.js",
  "scripts": { "build": "tsc", "start": "node dist/server.js", "dev": "ts-node src/server.ts" },
  "dependencies": {
    "express": "^4.18.2"
  },
  "devDependencies": {
    "@types/express": "^4.17.21",
    "@types/node": "^20.11.30",
    "ts-node": "^10.9.2",
    "typescript": "^5.4.3"
  }
}
'''

TSCONFIG_V1 = '''{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "rootDir": "src",
    "outDir": "dist",
    "strict": true,
    "esModuleInterop": true
  },
  "include": ["src"]
}
'''

TS_RENAMES = {f"src/{p}.js": f"src/{p}.ts" for p in (
    "server", "app", "models/task.model", "models/project.model", "repositories/task.repository",
    "repositories/project.repository", "services/task.service", "services/project.service",
    "controllers/task.controller", "controllers/project.controller")}

TASK_MODEL_TS = '''export type TaskStatus = 'open' | 'in_progress' | 'done' | 'archived';

export interface Task {
  id: number;
  title: string;
  projectId: number;
  assigneeId: number | null;
  dueDate: Date | null;
  status: TaskStatus;
  createdAt: Date;
}

export interface NewTask {
  title: string;
  projectId: number;
  dueDate?: string;
}
'''

PROJECT_MODEL_TS = '''export interface Project {
  id: number;
  name: string;
  ownerId: number;
  archived: boolean;
}

export interface NewProject {
  name: string;
  ownerId: number;
}
'''

TASK_REPO_TS_MEM = '''import { NewTask, Task, TaskStatus } from '../models/task.model';

export class TaskRepository {
  private readonly tasks = new Map<number, Task>();
  private nextId = 1;

  async findAll(): Promise<Task[]> {
    return Array.from(this.tasks.values());
  }

  async findById(id: number): Promise<Task | null> {
    return this.tasks.get(id) ?? null;
  }

  async create(input: NewTask): Promise<Task> {
    const task: Task = {
      id: this.nextId++, title: input.title.trim(), projectId: input.projectId, assigneeId: null,
      dueDate: input.dueDate ? new Date(input.dueDate) : null, status: 'open', createdAt: new Date(),
    };
    this.tasks.set(task.id, task);
    return task;
  }

  async setStatus(id: number, status: TaskStatus): Promise<Task | null> {
    const task = this.tasks.get(id);
    if (!task) return null;
    task.status = status;
    return task;
  }
}
'''

PROJECT_REPO_TS_MEM = '''import { NewProject, Project } from '../models/project.model';

export class ProjectRepository {
  private readonly projects = new Map<number, Project>();
  private nextId = 1;

  async findAll(): Promise<Project[]> {
    return Array.from(this.projects.values()).filter((p) => !p.archived);
  }

  async findById(id: number): Promise<Project | null> {
    return this.projects.get(id) ?? null;
  }

  async create(input: NewProject): Promise<Project> {
    const project: Project = { id: this.nextId++, name: input.name.trim(), ownerId: input.ownerId, archived: false };
    this.projects.set(project.id, project);
    return project;
  }
}
'''

TASK_SERVICE_TS_V1 = '''import { NewTask, Task } from '../models/task.model';
import { TaskRepository } from '../repositories/task.repository';

export class NotFoundError extends Error {}

export class TaskService {
  constructor(private readonly tasks: TaskRepository) {}

  list(): Promise<Task[]> {
    return this.tasks.findAll();
  }

  async add(input: NewTask): Promise<Task> {
    if (!input.title?.trim()) throw new Error('title is required');
    return this.tasks.create(input);
  }

  async complete(id: number): Promise<Task> {
    const task = await this.tasks.setStatus(id, 'done');
    if (!task) throw new NotFoundError(`task ${id} not found`);
    return task;
  }
}
'''

PROJECT_SERVICE_TS_V1 = '''import { NewProject, Project } from '../models/project.model';
import { ProjectRepository } from '../repositories/project.repository';

export class ProjectService {
  constructor(private readonly projects: ProjectRepository) {}

  list(): Promise<Project[]> {
    return this.projects.findAll();
  }

  async add(input: NewProject): Promise<Project> {
    if (!input.name?.trim()) throw new Error('name is required');
    return this.projects.create(input);
  }
}
'''

TASK_CONTROLLER_TS_V1 = '''import { Request, Response } from 'express';
import { NotFoundError, TaskService } from '../services/task.service';

export class TaskController {
  constructor(private readonly taskService: TaskService) {}

  async list(_req: Request, res: Response) {
    res.json(await this.taskService.list());
  }

  async create(req: Request, res: Response) {
    try {
      res.status(201).json(await this.taskService.add(req.body));
    } catch (err) {
      res.status(400).json({ error: (err as Error).message });
    }
  }

  async complete(req: Request, res: Response) {
    try {
      res.json(await this.taskService.complete(Number(req.params.id)));
    } catch (err) {
      res.status(err instanceof NotFoundError ? 404 : 500).json({ error: (err as Error).message });
    }
  }
}
'''

PROJECT_CONTROLLER_TS_V1 = '''import { Request, Response } from 'express';
import { ProjectService } from '../services/project.service';

export class ProjectController {
  constructor(private readonly projectService: ProjectService) {}

  async list(_req: Request, res: Response) {
    res.json(await this.projectService.list());
  }

  async create(req: Request, res: Response) {
    try {
      res.status(201).json(await this.projectService.add(req.body));
    } catch (err) {
      res.status(400).json({ error: (err as Error).message });
    }
  }
}
'''

APP_TS_V1 = '''import express from 'express';
import { ProjectController } from './controllers/project.controller';
import { TaskController } from './controllers/task.controller';
import { ProjectRepository } from './repositories/project.repository';
import { TaskRepository } from './repositories/task.repository';
import { ProjectService } from './services/project.service';
import { TaskService } from './services/task.service';

const tasks = new TaskController(new TaskService(new TaskRepository()));
const projects = new ProjectController(new ProjectService(new ProjectRepository()));

export const app = express();
app.use(express.json());

app.get('/tasks', (req, res) => tasks.list(req, res));
app.post('/tasks', (req, res) => tasks.create(req, res));
app.post('/tasks/:id/complete', (req, res) => tasks.complete(req, res));
app.get('/projects', (req, res) => projects.list(req, res));
app.post('/projects', (req, res) => projects.create(req, res));
'''

SERVER_TS = '''import { app } from './app';

const port = Number(process.env.PORT ?? 3000);
app.listen(port, () => console.log(`TaskFlow listening on ${port}`));
'''

# ------------------------------------------------------------------ Postgres via pg

PKG_PG = PKG_TS.replace('''    "express": "^4.18.2"
  },''', '''    "express": "^4.18.2",
    "pg": "^8.11.3"
  },''').replace('''    "@types/node": "^20.11.30",''', '''    "@types/node": "^20.11.30",
    "@types/pg": "^8.11.4",''')

POOL = '''import { Pool } from 'pg';

export const pool = new Pool({ connectionString: process.env.DATABASE_URL ?? 'postgres://localhost/taskflow' });
'''

TASK_REPO_PG = '''import { pool } from '../db/pool';
import { NewTask, Task, TaskStatus } from '../models/task.model';

function toTask(row: any): Task {
  return { id: row.id, title: row.title, projectId: row.project_id, assigneeId: row.assignee_id,
           dueDate: row.due_date, status: row.status, createdAt: row.created_at };
}

export class TaskRepository {
  async findAll(): Promise<Task[]> {
    const { rows } = await pool.query('SELECT * FROM tasks ORDER BY created_at DESC');
    return rows.map(toTask);
  }

  async findById(id: number): Promise<Task | null> {
    const { rows } = await pool.query('SELECT * FROM tasks WHERE id = $1', [id]);
    return rows[0] ? toTask(rows[0]) : null;
  }

  async create(input: NewTask): Promise<Task> {
    const { rows } = await pool.query(
      'INSERT INTO tasks (title, project_id, due_date, status) VALUES ($1, $2, $3, $4) RETURNING *',
      [input.title.trim(), input.projectId, input.dueDate ?? null, 'open']);
    return toTask(rows[0]);
  }

  async setStatus(id: number, status: TaskStatus): Promise<Task | null> {
    const { rows } = await pool.query('UPDATE tasks SET status = $1 WHERE id = $2 RETURNING *', [status, id]);
    return rows[0] ? toTask(rows[0]) : null;
  }
}
'''

PROJECT_REPO_PG = '''import { pool } from '../db/pool';
import { NewProject, Project } from '../models/project.model';

function toProject(row: any): Project {
  return { id: row.id, name: row.name, ownerId: row.owner_id, archived: row.archived };
}

export class ProjectRepository {
  async findAll(): Promise<Project[]> {
    const { rows } = await pool.query('SELECT * FROM projects WHERE archived = false ORDER BY name');
    return rows.map(toProject);
  }

  async findById(id: number): Promise<Project | null> {
    const { rows } = await pool.query('SELECT * FROM projects WHERE id = $1', [id]);
    return rows[0] ? toProject(rows[0]) : null;
  }

  async create(input: NewProject): Promise<Project> {
    const { rows } = await pool.query('INSERT INTO projects (name, owner_id) VALUES ($1, $2) RETURNING *',
      [input.name.trim(), input.ownerId]);
    return toProject(rows[0]);
  }
}
'''

# ------------------------------------------------------------------ zod

PKG_ZOD = PKG_PG.replace('''    "pg": "^8.11.3"''', '''    "pg": "^8.11.3",
    "zod": "^3.22.4"''')

TASK_SCHEMA = '''import { z } from 'zod';

export const newTaskSchema = z.object({
  title: z.string().trim().min(1).max(200),
  projectId: z.number().int().positive(),
  dueDate: z.string().datetime().optional(),
});
'''

PROJECT_SCHEMA = '''import { z } from 'zod';

export const newProjectSchema = z.object({
  name: z.string().trim().min(1).max(120),
  ownerId: z.number().int().positive(),
});
'''

TASK_CONTROLLER_TS_V2 = TASK_CONTROLLER_TS_V1.replace(
    "import { NotFoundError, TaskService } from '../services/task.service';\n",
    "import { NotFoundError, TaskService } from '../services/task.service';\n"
    "import { newTaskSchema } from '../validation/task.schema';\n").replace(
    '''      res.status(201).json(await this.taskService.add(req.body));''',
    '''      const input = newTaskSchema.parse(req.body);
      res.status(201).json(await this.taskService.add(input));''')

PROJECT_CONTROLLER_TS_V2 = PROJECT_CONTROLLER_TS_V1.replace(
    "import { ProjectService } from '../services/project.service';\n",
    "import { ProjectService } from '../services/project.service';\n"
    "import { newProjectSchema } from '../validation/project.schema';\n").replace(
    '''      res.status(201).json(await this.projectService.add(req.body));''',
    '''      res.status(201).json(await this.projectService.add(newProjectSchema.parse(req.body)));''')

# ------------------------------------------------------------------ Prisma replaces pg

PKG_PRISMA = PKG_ZOD.replace('''    "pg": "^8.11.3",
''', '''    "@prisma/client": "^5.11.0",
''').replace('''    "@types/pg": "^8.11.4",
''', '').replace('''    "@types/node": "^20.11.30",''', '''    "@types/node": "^20.11.30",
    "prisma": "^5.11.0",''')

SCHEMA_PRISMA = '''generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model Project {
  id       Int     @id @default(autoincrement())
  name     String
  ownerId  Int
  archived Boolean @default(false)
  tasks    Task[]
}

model Task {
  id         Int       @id @default(autoincrement())
  title      String
  projectId  Int
  project    Project   @relation(fields: [projectId], references: [id])
  assigneeId Int?
  dueDate    DateTime?
  status     String    @default("open")
  createdAt  DateTime  @default(now())
}

model User {
  id    Int    @id @default(autoincrement())
  email String @unique
  name  String
}
'''

PRISMA_CLIENT = '''import { PrismaClient } from '@prisma/client';

export const prisma = new PrismaClient();
'''

TASK_REPO_PRISMA = '''import { prisma } from '../db/prisma';
import { NewTask, Task, TaskStatus } from '../models/task.model';

export class TaskRepository {
  findAll(): Promise<Task[]> {
    return prisma.task.findMany({ orderBy: { createdAt: 'desc' } }) as Promise<Task[]>;
  }

  findById(id: number): Promise<Task | null> {
    return prisma.task.findUnique({ where: { id } }) as Promise<Task | null>;
  }

  create(input: NewTask): Promise<Task> {
    return prisma.task.create({
      data: { title: input.title.trim(), projectId: input.projectId, dueDate: input.dueDate ? new Date(input.dueDate) : null },
    }) as Promise<Task>;
  }

  async setStatus(id: number, status: TaskStatus): Promise<Task | null> {
    const found = await this.findById(id);
    if (!found) return null;
    return prisma.task.update({ where: { id }, data: { status } }) as Promise<Task>;
  }
}
'''

PROJECT_REPO_PRISMA = '''import { prisma } from '../db/prisma';
import { NewProject, Project } from '../models/project.model';

export class ProjectRepository {
  findAll(): Promise<Project[]> {
    return prisma.project.findMany({ where: { archived: false }, orderBy: { name: 'asc' } });
  }

  findById(id: number): Promise<Project | null> {
    return prisma.project.findUnique({ where: { id } });
  }

  create(input: NewProject): Promise<Project> {
    return prisma.project.create({ data: { name: input.name.trim(), ownerId: input.ownerId } });
  }
}
'''

# ------------------------------------------------------------------ users and assignment

USER_MODEL_TS = '''export interface User {
  id: number;
  email: string;
  name: string;
}
'''

USER_REPO_PRISMA = '''import { prisma } from '../db/prisma';
import { User } from '../models/user.model';

export class UserRepository {
  findById(id: number): Promise<User | null> {
    return prisma.user.findUnique({ where: { id } });
  }

  findByEmail(email: string): Promise<User | null> {
    return prisma.user.findUnique({ where: { email: email.toLowerCase() } });
  }

  create(email: string, name: string): Promise<User> {
    return prisma.user.create({ data: { email: email.toLowerCase(), name } });
  }
}
'''

USER_SERVICE_TS = '''import { User } from '../models/user.model';
import { UserRepository } from '../repositories/user.repository';

export class UserService {
  constructor(private readonly users: UserRepository) {}

  async register(email: string, name: string): Promise<User> {
    if (await this.users.findByEmail(email)) throw new Error('email already registered');
    return this.users.create(email, name.trim());
  }

  async get(id: number): Promise<User | null> {
    return this.users.findById(id);
  }
}
'''

USER_CONTROLLER_TS = '''import { Request, Response } from 'express';
import { UserService } from '../services/user.service';

export class UserController {
  constructor(private readonly userService: UserService) {}

  async register(req: Request, res: Response) {
    try {
      res.status(201).json(await this.userService.register(req.body.email, req.body.name));
    } catch (err) {
      res.status(409).json({ error: (err as Error).message });
    }
  }

  async get(req: Request, res: Response) {
    const user = await this.userService.get(Number(req.params.id));
    return user ? res.json(user) : res.status(404).json({ error: 'user not found' });
  }
}
'''

TASK_REPO_PRISMA_V2 = TASK_REPO_PRISMA.replace('''  async setStatus(''', '''  assign(id: number, assigneeId: number): Promise<Task> {
    return prisma.task.update({ where: { id }, data: { assigneeId } }) as Promise<Task>;
  }

  async countOpenByProject(projectIds: number[]): Promise<Record<number, number>> {
    const rows = await prisma.task.groupBy({
      by: ['projectId'], where: { projectId: { in: projectIds }, status: { in: ['open', 'in_progress'] } }, _count: true,
    });
    return Object.fromEntries(rows.map((r) => [r.projectId, r._count]));
  }

  async setStatus(''')

TASK_SERVICE_TS_V2 = '''import { NewTask, Task } from '../models/task.model';
import { TaskRepository } from '../repositories/task.repository';
import { UserService } from './user.service';

export class NotFoundError extends Error {}

export class TaskService {
  constructor(private readonly tasks: TaskRepository, private readonly users: UserService) {}

  list(): Promise<Task[]> {
    return this.tasks.findAll();
  }

  async add(input: NewTask): Promise<Task> {
    if (!input.title?.trim()) throw new Error('title is required');
    return this.tasks.create(input);
  }

  async assign(id: number, userId: number): Promise<Task> {
    if (!(await this.users.get(userId))) throw new NotFoundError(`user ${userId} not found`);
    if (!(await this.tasks.findById(id))) throw new NotFoundError(`task ${id} not found`);
    return this.tasks.assign(id, userId);
  }

  async complete(id: number): Promise<Task> {
    const task = await this.tasks.setStatus(id, 'done');
    if (!task) throw new NotFoundError(`task ${id} not found`);
    return task;
  }
}
'''

TASK_CONTROLLER_TS_V3 =TASK_CONTROLLER_TS_V2.replace('''  async complete(req: Request, res: Response) {''', '''  async assign(req: Request, res: Response) {
    try {
      res.json(await this.taskService.assign(Number(req.params.id), Number(req.body.userId)));
    } catch (err) {
      res.status(err instanceof NotFoundError ? 404 : 400).json({ error: (err as Error).message });
    }
  }

  async complete(req: Request, res: Response) {''')

APP_TS_V2 = '''import express from 'express';
import { ProjectController } from './controllers/project.controller';
import { TaskController } from './controllers/task.controller';
import { UserController } from './controllers/user.controller';
import { ProjectRepository } from './repositories/project.repository';
import { TaskRepository } from './repositories/task.repository';
import { UserRepository } from './repositories/user.repository';
import { ProjectService } from './services/project.service';
import { TaskService } from './services/task.service';
import { UserService } from './services/user.service';

const userService = new UserService(new UserRepository());
const tasks = new TaskController(new TaskService(new TaskRepository(), userService));
const projects = new ProjectController(new ProjectService(new ProjectRepository()));
const users = new UserController(userService);

export const app = express();
app.use(express.json());

app.get('/tasks', (req, res) => tasks.list(req, res));
app.post('/tasks', (req, res) => tasks.create(req, res));
app.post('/tasks/:id/assign', (req, res) => tasks.assign(req, res));
app.post('/tasks/:id/complete', (req, res) => tasks.complete(req, res));
app.get('/projects', (req, res) => projects.list(req, res));
app.post('/projects', (req, res) => projects.create(req, res));
app.post('/users', (req, res) => users.register(req, res));
app.get('/users/:id', (req, res) => users.get(req, res));
'''

# ------------------------------------------------------------------ @app alias and barrels

TSCONFIG_V2 = '''{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "rootDir": "src",
    "outDir": "dist",
    "strict": true,
    "esModuleInterop": true,
    "baseUrl": ".",
    "paths": {
      "@app/*": ["src/*"]
    }
  },
  "include": ["src"]
}
'''

REPOS_BARREL = '''export { ProjectRepository } from './project.repository';
export { TaskRepository } from './task.repository';
export { UserRepository } from './user.repository';
'''

SERVICES_BARREL = '''export { ProjectService } from './project.service';
export { NotFoundError, TaskService } from './task.service';
export { UserService } from './user.service';
'''

APP_TS_V3 = '''import express from 'express';
import { ProjectController } from '@app/controllers/project.controller';
import { TaskController } from '@app/controllers/task.controller';
import { UserController } from '@app/controllers/user.controller';
import { ProjectRepository, TaskRepository, UserRepository } from '@app/repositories';
import { ProjectService, TaskService, UserService } from '@app/services';

const userService = new UserService(new UserRepository());
const tasks = new TaskController(new TaskService(new TaskRepository(), userService));
const projects = new ProjectController(new ProjectService(new ProjectRepository()));
const users = new UserController(userService);

export const app = express();
app.use(express.json());

app.get('/tasks', (req, res) => tasks.list(req, res));
app.post('/tasks', (req, res) => tasks.create(req, res));
app.post('/tasks/:id/assign', (req, res) => tasks.assign(req, res));
app.post('/tasks/:id/complete', (req, res) => tasks.complete(req, res));
app.get('/projects', (req, res) => projects.list(req, res));
app.post('/projects', (req, res) => projects.create(req, res));
app.post('/users', (req, res) => users.register(req, res));
app.get('/users/:id', (req, res) => users.get(req, res));
'''

TASK_CONTROLLER_TS_V4 = TASK_CONTROLLER_TS_V3.replace(
    "import { NotFoundError, TaskService } from '../services/task.service';\n"
    "import { newTaskSchema } from '../validation/task.schema';\n",
    "import { NotFoundError, TaskService } from '@app/services';\n"
    "import { newTaskSchema } from '@app/validation/task.schema';\n")

PROJECT_CONTROLLER_TS_V3 = PROJECT_CONTROLLER_TS_V2.replace(
    "import { ProjectService } from '../services/project.service';\n"
    "import { newProjectSchema } from '../validation/project.schema';\n",
    "import { ProjectService } from '@app/services';\n"
    "import { newProjectSchema } from '@app/validation/project.schema';\n")

# ------------------------------------------------------------------ event bus

EVENT_BUS = '''type Handler<T> = (event: T) => Promise<void> | void;

export class EventBus {
  private readonly handlers = new Map<string, Handler<any>[]>();

  subscribe<T>(type: string, handler: Handler<T>): void {
    this.handlers.set(type, [...(this.handlers.get(type) ?? []), handler]);
  }

  async publish<T>(type: string, event: T): Promise<void> {
    for (const handler of this.handlers.get(type) ?? []) {
      await handler(event);
    }
  }
}

export const eventBus = new EventBus();
'''

TASK_EVENTS = '''export const TASK_COMPLETED = 'task.completed';
export const TASK_ASSIGNED = 'task.assigned';

export interface TaskCompleted {
  taskId: number;
  projectId: number;
  completedAt: Date;
}

export interface TaskAssigned {
  taskId: number;
  assigneeId: number;
}
'''

NOTIFY_HANDLER = '''import { UserRepository } from '@app/repositories';
import { TaskAssigned } from '../task-events';

export function notifyAssignee(users: UserRepository) {
  return async (event: TaskAssigned) => {
    const user = await users.findById(event.assigneeId);
    if (user) console.log(`notify ${user.email}: task ${event.taskId} is yours`);
  };
}
'''

EVENTS_INDEX = '''import { UserRepository } from '@app/repositories';
import { eventBus } from './event-bus';
import { notifyAssignee } from './listeners/notify-assignee';
import { TASK_ASSIGNED } from './task-events';

export function registerHandlers(users: UserRepository): void {
  eventBus.subscribe(TASK_ASSIGNED, notifyAssignee(users));
}

export { eventBus } from './event-bus';
export * from './task-events';
'''

TASK_SERVICE_TS_V3 = '''import { EventBus, TASK_ASSIGNED, TASK_COMPLETED, TaskAssigned, TaskCompleted } from '@app/events';
import { NewTask, Task } from '@app/models/task.model';
import { TaskRepository } from '@app/repositories';
import { UserService } from './user.service';

export class NotFoundError extends Error {}

export class TaskService {
  constructor(private readonly tasks: TaskRepository, private readonly users: UserService,
              private readonly events: EventBus) {}

  list(): Promise<Task[]> {
    return this.tasks.findAll();
  }

  async add(input: NewTask): Promise<Task> {
    if (!input.title?.trim()) throw new Error('title is required');
    return this.tasks.create(input);
  }

  async assign(id: number, userId: number): Promise<Task> {
    if (!(await this.users.get(userId))) throw new NotFoundError(`user ${userId} not found`);
    if (!(await this.tasks.findById(id))) throw new NotFoundError(`task ${id} not found`);
    const task = await this.tasks.assign(id, userId);
    await this.events.publish<TaskAssigned>(TASK_ASSIGNED, { taskId: id, assigneeId: userId });
    return task;
  }

  async complete(id: number): Promise<Task> {
    const task = await this.tasks.setStatus(id, 'done');
    if (!task) throw new NotFoundError(`task ${id} not found`);
    await this.events.publish<TaskCompleted>(TASK_COMPLETED, { taskId: id, projectId: task.projectId,
                                                               completedAt: new Date() });
    return task;
  }
}
'''

APP_TS_V4 = APP_TS_V3.replace(
    "import { ProjectService, TaskService, UserService } from '@app/services';\n",
    "import { ProjectService, TaskService, UserService } from '@app/services';\n"
    "import { eventBus, registerHandlers } from '@app/events';\n").replace(
    '''const userService = new UserService(new UserRepository());
const tasks = new TaskController(new TaskService(new TaskRepository(), userService));''',
    '''const userRepository = new UserRepository();
const userService = new UserService(userRepository);
registerHandlers(userRepository);
const tasks = new TaskController(new TaskService(new TaskRepository(), userService, eventBus));''')

# ------------------------------------------------------------------ tests and CI

PKG_JEST = PKG_PRISMA.replace('''"dev": "ts-node src/server.ts" },''', '''"dev": "ts-node src/server.ts", "test": "jest" },''').replace(
    '''    "@types/express": "^4.17.21",''', '''    "@types/express": "^4.17.21",
    "@types/jest": "^29.5.12",''').replace('''    "prisma": "^5.11.0",''', '''    "jest": "^29.7.0",
    "prisma": "^5.11.0",
    "ts-jest": "^29.1.2",''')

JEST_CONFIG = '''module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  moduleNameMapper: { '^@app/(.*)$': '<rootDir>/src/$1' },
};
'''

TASK_SERVICE_TEST = '''import { EventBus } from '@app/events';
import { TaskService } from '@app/services';

const repo = {
  findById: jest.fn(async (id: number) => ({ id, projectId: 1, status: 'open' })),
  setStatus: jest.fn(async (id: number, status: string) => ({ id, projectId: 1, status })),
  assign: jest.fn(async (id: number, assigneeId: number) => ({ id, assigneeId })),
};
const users = { get: jest.fn(async (id: number) => (id === 7 ? { id } : null)) };

describe('TaskService', () => {
  it('publishes an event when a task is completed', async () => {
    const bus = new EventBus();
    const seen: unknown[] = [];
    bus.subscribe('task.completed', (e) => { seen.push(e); });
    const service = new TaskService(repo as any, users as any, bus);
    await service.complete(3);
    expect(seen).toHaveLength(1);
  });

  it('refuses to assign to an unknown user', async () => {
    const service = new TaskService(repo as any, users as any, new EventBus());
    await expect(service.assign(3, 99)).rejects.toThrow('user 99 not found');
  });
});
'''

CI_NODE = '''name: tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
      - run: npm ci
      - run: npx prisma generate
      - run: npm test
'''

# ------------------------------------------------------------------ drift

TASK_CONTROLLER_DRIFT = TASK_CONTROLLER_TS_V4.replace(
    "import { NotFoundError, TaskService } from '@app/services';\n",
    "import { prisma } from '@app/db/prisma';\nimport { NotFoundError, TaskService } from '@app/services';\n").replace(
    '''  async complete(req: Request, res: Response) {''', '''  async archive(req: Request, res: Response) {
    // Hotfix for the demo on Friday: archive straight through Prisma.
    const task = await prisma.task.update({ where: { id: Number(req.params.id) }, data: { status: 'archived' } });
    res.json(task);
  }

  async complete(req: Request, res: Response) {''')

APP_TS_V5 = APP_TS_V4.replace(
    "app.post('/tasks/:id/complete', (req, res) => tasks.complete(req, res));\n",
    "app.post('/tasks/:id/complete', (req, res) => tasks.complete(req, res));\n"
    "app.post('/tasks/:id/archive', (req, res) => tasks.archive(req, res));\n")

PROJECT_CONTROLLER_DRIFT = '''import { Request, Response } from 'express';
import { TaskRepository } from '@app/repositories';
import { ProjectService } from '@app/services';
import { newProjectSchema } from '@app/validation/project.schema';

export class ProjectController {
  constructor(private readonly projectService: ProjectService, private readonly tasks: TaskRepository) {}

  async list(_req: Request, res: Response) {
    const projects = await this.projectService.list();
    // The project page shows open-task counts; read them straight from the task table.
    const counts = await this.tasks.countOpenByProject(projects.map((p) => p.id));
    res.json(projects.map((p) => ({ ...p, openTasks: counts[p.id] ?? 0 })));
  }

  async create(req: Request, res: Response) {
    try {
      res.status(201).json(await this.projectService.add(newProjectSchema.parse(req.body)));
    } catch (err) {
      res.status(400).json({ error: (err as Error).message });
    }
  }
}
'''

APP_TS_V6 = APP_TS_V5.replace(
    '''const tasks = new TaskController(new TaskService(new TaskRepository(), userService, eventBus));
const projects = new ProjectController(new ProjectService(new ProjectRepository()));''',
    '''const taskRepository = new TaskRepository();
const tasks = new TaskController(new TaskService(taskRepository, userService, eventBus));
const projects = new ProjectController(new ProjectService(new ProjectRepository()), taskRepository);''')

TASK_REPO_PRISMA_V3 = TASK_REPO_PRISMA_V2.replace('''  async countOpenByProject(projectIds: number[])''', '''  archive(id: number): Promise<Task> {
    return prisma.task.update({ where: { id }, data: { status: 'archived' } }) as Promise<Task>;
  }

  async countOpenByProject(projectIds: number[])''')

TASK_SERVICE_TS_V4 = TASK_SERVICE_TS_V3.replace('''  async complete(id: number): Promise<Task> {''', '''  async archive(id: number): Promise<Task> {
    if (!(await this.tasks.findById(id))) throw new NotFoundError(`task ${id} not found`);
    return this.tasks.archive(id);
  }

  async complete(id: number): Promise<Task> {''')

TASK_CONTROLLER_FIXED = TASK_CONTROLLER_TS_V4.replace('''  async complete(req: Request, res: Response) {''', '''  async archive(req: Request, res: Response) {
    try {
      res.json(await this.taskService.archive(Number(req.params.id)));
    } catch (err) {
      res.status(err instanceof NotFoundError ? 404 : 500).json({ error: (err as Error).message });
    }
  }

  async complete(req: Request, res: Response) {''')

README_TS = '''# TaskFlow

Task and project tracking API (Express + TypeScript + Prisma).

## Architecture

```
src/controllers   HTTP handlers - call services only
src/services      business rules; publish domain events
src/repositories  data access through Prisma
src/events        in-process event bus and its handlers
src/models        shared types
src/validation    zod request schemas
```

Imports use the `@app/*` alias (tsconfig `paths`) and the barrels in
`src/repositories` and `src/services`.

## Run

```
npm install
npx prisma migrate dev
npm run dev
```
'''

STORY = [
    {"when": "2026-01-06T09:30:00-03:00", "author": ANA, "message": "Initial Express API for tasks",
     "files": {"package.json": PKG_V1, ".gitignore": "node_modules/\ndist/\n.env\n", "src/server.js": SERVER_JS,
               "src/app.js": APP_JS_V1, "src/models/task.model.js": TASK_MODEL_JS,
               "src/repositories/task.repository.js": TASK_REPO_JS, "src/services/task.service.js": TASK_SERVICE_JS,
               "src/controllers/task.controller.js": TASK_CONTROLLER_JS}},
    {"when": "2026-01-10T14:15:00-03:00", "author": ANA, "message": "Add projects",
     "files": {"src/models/project.model.js": PROJECT_MODEL_JS, "src/repositories/project.repository.js": PROJECT_REPO_JS,
               "src/services/project.service.js": PROJECT_SERVICE_JS,
               "src/controllers/project.controller.js": PROJECT_CONTROLLER_JS, "src/app.js": APP_JS_V2}},
    {"when": "2026-01-19T11:00:00+09:00", "author": KENJI,
     "message": "Move the codebase to TypeScript\n\nRenames every source file to .ts and adds the compiler. "
                "Two production bugs this month were a missing field and a string id compared to a number; "
                "strict types catch both. The code itself is converted in the next commit.",
     "rename": TS_RENAMES, "files": {"package.json": PKG_TS, "tsconfig.json": TSCONFIG_V1}},
    {"when": "2026-01-21T16:40:00+09:00", "author": KENJI,
     "message": "Rewrite layers as classes with async/await\n\nThe callback pyramids made error handling "
                "inconsistent (some errors were swallowed, some answered twice). Services and repositories are "
                "classes now, wired by constructor injection in app.ts, and every method returns a Promise.",
     "files": {"src/server.ts": SERVER_TS, "src/app.ts": APP_TS_V1, "src/models/task.model.ts": TASK_MODEL_TS,
               "src/models/project.model.ts": PROJECT_MODEL_TS, "src/repositories/task.repository.ts": TASK_REPO_TS_MEM,
               "src/repositories/project.repository.ts": PROJECT_REPO_TS_MEM,
               "src/services/task.service.ts": TASK_SERVICE_TS_V1, "src/services/project.service.ts": PROJECT_SERVICE_TS_V1,
               "src/controllers/task.controller.ts": TASK_CONTROLLER_TS_V1,
               "src/controllers/project.controller.ts": PROJECT_CONTROLLER_TS_V1}},
    {"when": "2026-02-03T10:20:00-03:00", "author": ANA,
     "message": "Store tasks and projects in Postgres\n\nThe in-memory maps lost everything on every deploy. "
                "Repositories now use node-postgres with a shared pool.",
     "files": {"package.json": PKG_PG, "src/db/pool.ts": POOL, "src/repositories/task.repository.ts": TASK_REPO_PG,
               "src/repositories/project.repository.ts": PROJECT_REPO_PG}},
    {"when": "2026-02-12T13:05:00+01:00", "author": LEILA,
     "message": "Validate request bodies with zod",
     "files": {"package.json": PKG_ZOD, "src/validation/task.schema.ts": TASK_SCHEMA,
               "src/validation/project.schema.ts": PROJECT_SCHEMA,
               "src/controllers/task.controller.ts": TASK_CONTROLLER_TS_V2,
               "src/controllers/project.controller.ts": PROJECT_CONTROLLER_TS_V2}},
    {"when": "2026-02-26T09:45:00-03:00", "author": ANA,
     "message": "Replace pg with Prisma\n\nHand-written SQL and row mappers drifted from the schema twice "
                "(due_date came back as a string). Prisma generates typed queries from schema.prisma and "
                "gives us migrations; the pg pool is gone.",
     "delete": ["src/db/pool.ts"],
     "files": {"package.json": PKG_PRISMA, "prisma/schema.prisma": SCHEMA_PRISMA, "src/db/prisma.ts": PRISMA_CLIENT,
               "src/repositories/task.repository.ts": TASK_REPO_PRISMA,
               "src/repositories/project.repository.ts": PROJECT_REPO_PRISMA}},
    {"when": "2026-03-09T15:30:00+01:00", "author": LEILA, "message": "Users and task assignment",
     "files": {"src/models/user.model.ts": USER_MODEL_TS, "src/repositories/user.repository.ts": USER_REPO_PRISMA,
               "src/services/user.service.ts": USER_SERVICE_TS, "src/controllers/user.controller.ts": USER_CONTROLLER_TS,
               "src/repositories/task.repository.ts": TASK_REPO_PRISMA_V2,
               "src/services/task.service.ts": TASK_SERVICE_TS_V2,
               "src/controllers/task.controller.ts": TASK_CONTROLLER_TS_V3, "src/app.ts": APP_TS_V2}},
    {"when": "2026-03-16T11:10:00+09:00", "author": KENJI,
     "message": "Import through the @app alias and barrel files\n\nRelative paths like ../../services were "
                "breaking on every move. tsconfig maps @app/* to src/*, and repositories and services export "
                "from one index each.",
     "files": {"tsconfig.json": TSCONFIG_V2, "src/repositories/index.ts": REPOS_BARREL,
               "src/services/index.ts": SERVICES_BARREL, "src/app.ts": APP_TS_V3,
               "src/controllers/task.controller.ts": TASK_CONTROLLER_TS_V4,
               "src/controllers/project.controller.ts": PROJECT_CONTROLLER_TS_V3}},
    {"when": "2026-03-24T17:00:00+01:00", "author": LEILA,
     "message": "Introduce a domain event bus\n\nNotifications were about to be called from inside TaskService. "
                "Services now publish task.assigned / task.completed events and handlers in src/events react, "
                "so new reactions (email, webhooks, analytics) don't touch the service.",
     "files": {"src/events/event-bus.ts": EVENT_BUS, "src/events/task-events.ts": TASK_EVENTS,
               "src/events/listeners/notify-assignee.ts": NOTIFY_HANDLER, "src/events/index.ts": EVENTS_INDEX,
               "src/services/task.service.ts": TASK_SERVICE_TS_V3, "src/app.ts": APP_TS_V4}},
    {"when": "2026-04-01T10:00:00-03:00", "author": ANA, "message": "Jest tests for TaskService",
     "files": {"package.json": PKG_JEST, "jest.config.js": JEST_CONFIG,
               "tests/task.service.test.ts": TASK_SERVICE_TEST}},
    {"when": "2026-04-03T12:30:00-03:00", "author": ANA, "message": "Run tests in GitHub Actions",
     "files": {".github/workflows/tests.yml": CI_NODE}},
    {"when": "2026-04-10T19:20:00+09:00", "author": KENJI, "message": "Hotfix: archive tasks",
     "files": {"src/controllers/task.controller.ts": TASK_CONTROLLER_DRIFT, "src/app.ts": APP_TS_V5}},
    {"when": "2026-05-06T14:45:00+01:00", "author": LEILA, "message": "Open-task counts on the project list",
     "files": {"src/controllers/project.controller.ts": PROJECT_CONTROLLER_DRIFT, "src/app.ts": APP_TS_V6}},
    {"when": "2026-04-22T09:15:00-03:00", "author": ANA,
     "message": "Move task archiving into TaskService\n\nThe archive hotfix wrote through Prisma from the "
                "controller, skipping the not-found check and the service's rules.",
     "files": {"src/repositories/task.repository.ts": TASK_REPO_PRISMA_V3,
               "src/services/task.service.ts": TASK_SERVICE_TS_V4,
               "src/controllers/task.controller.ts": TASK_CONTROLLER_FIXED}},
    {"when": "2026-05-20T16:00:00+09:00", "author": KENJI, "message": "README with the architecture overview",
     "files": {"README.md": README_TS}},
]

# Steps are listed by topic; commit them in date order (dates carry different time zones).
STORY.sort(key=lambda step: datetime.fromisoformat(step["when"]))

# ------------------------------------------------------------------ live code-review demo

BAD_TASK_SERVICE = TASK_SERVICE_TS_V4.replace('''  async complete(id: number): Promise<Task> {
    const task = await this.tasks.setStatus(id, 'done');
    if (!task) throw new NotFoundError(`task ${id} not found`);''', '''  async reopen(id: number): Promise<Task> {
    const task = this.tasks.findById(id);
    if (task.status = 'archived') throw new Error('archived tasks cannot be reopened');
    return (await this.tasks.setStatus(id, 'open'))!;
  }

  async complete(id: number): Promise<Task> {
    const task = await this.tasks.setStatus(id, 'done');
    if (!task) throw new NotFoundError(`task ${id} not found`);''')

BAD_USER_CONTROLLER = USER_CONTROLLER_TS.replace(
    "import { UserService } from '../services/user.service';\n",
    "import { prisma } from '@app/db/prisma';\nimport { UserService } from '../services/user.service';\n") + '''
export async function searchUsers(req: Request, res: Response) {
  const users = await prisma.$queryRawUnsafe(`SELECT id, email, name FROM "User" WHERE email LIKE '%${req.query.q}%'`);
  res.json(users);
}
'''

BAD_COMMIT = {
    "when": "2026-06-02T18:20:00+01:00", "author": LEILA,
    "message": "Reopen tasks and search users by email",
    "files": {"src/services/task.service.ts": BAD_TASK_SERVICE, "src/controllers/user.controller.ts": BAD_USER_CONTROLLER},
}

USER_REPO_SEARCH = USER_REPO_PRISMA.replace('''  create(email: string, name: string)''', '''  searchByEmail(fragment: string): Promise<User[]> {
    return prisma.user.findMany({ where: { email: { contains: fragment, mode: 'insensitive' } }, take: 50 });
  }

  create(email: string, name: string)''')

USER_SERVICE_SEARCH = USER_SERVICE_TS.replace(
    "import { UserRepository } from '../repositories/user.repository';\n",
    "import { UserRepository } from '../repositories/user.repository';\n\n"
    "export class InvalidSearchError extends Error {}\n").replace('''  async get(id: number)''', '''  search(fragment: string): Promise<User[]> {
    if (fragment.trim().length < 2) throw new InvalidSearchError('search needs at least 2 characters');
    return this.users.searchByEmail(fragment.trim());
  }

  async get(id: number)''')

FIXED_USER_CONTROLLER = USER_CONTROLLER_TS.replace(
    "import { UserService } from '../services/user.service';\n",
    "import { InvalidSearchError, UserService } from '../services/user.service';\n").replace('''  async get(req: Request, res: Response) {''', '''  async search(req: Request, res: Response) {
    try {
      res.json(await this.userService.search(String(req.query.q ?? '')));
    } catch (err) {
      const invalid = err instanceof InvalidSearchError;
      res.status(invalid ? 400 : 500).json({ error: invalid ? (err as Error).message : 'user search failed' });
    }
  }

  async get(req: Request, res: Response) {''')

# The fix removes the unfinished reopen() again (it returns with its own tests) and moves the
# user search behind the service.
FIXED_TASK_SERVICE = TASK_SERVICE_TS_V4

FIX_COMMIT = {
    "when": "2026-06-03T10:40:00-03:00", "author": ANA,
    "message": "Fix review findings: take out the unfinished reopen, search users through the service",
    "files": {"src/services/task.service.ts": FIXED_TASK_SERVICE, "src/controllers/user.controller.ts": FIXED_USER_CONTROLLER,
              "src/services/user.service.ts": USER_SERVICE_SEARCH, "src/repositories/user.repository.ts": USER_REPO_SEARCH},
}
