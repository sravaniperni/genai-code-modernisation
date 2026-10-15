import { Route, Routes } from 'react-router';
import { Layout } from './components/Layout';
import { DashboardPage } from './pages/DashboardPage';
import { EvaluationPage } from './pages/evaluation/EvaluationPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { RepositoriesPage } from './pages/repositories/RepositoriesPage';
import { SettingsPage } from './pages/SettingsPage';
import { TaskCreatePage } from './pages/tasks/TaskCreatePage';
import { TaskMonitorPage } from './pages/tasks/TaskMonitorPage';
import { TaskReviewPage } from './pages/tasks/TaskReviewPage';
import { TasksPage } from './pages/tasks/TasksPage';

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="repositories" element={<RepositoriesPage />} />
        <Route path="repositories/:repoId" element={<RepositoriesPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="tasks/new" element={<TaskCreatePage />} />
        <Route path="tasks/:taskId" element={<TaskMonitorPage />} />
        <Route path="tasks/:taskId/review" element={<TaskReviewPage />} />
        <Route path="evaluation" element={<EvaluationPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
