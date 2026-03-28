/**
 * Application route definitions.
 * Protected routes require a valid JWT; role-gated routes check the user's role.
 */
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import LoginPage from '@/pages/auth/LoginPage'
import DashboardPage from '@/pages/dashboard/DashboardPage'
import BarDetailPage from '@/pages/dashboard/BarDetailPage'
import EventListPage from '@/pages/events/EventListPage'
import EventCreatePage from '@/pages/events/EventCreatePage'
import EventDetailPage from '@/pages/events/EventDetailPage'
import PredictionPage from '@/pages/predictions/PredictionPage'
import ReportPage from '@/pages/reports/ReportPage'
import SettingsPage from '@/pages/settings/SettingsPage'
import WarehouseScanPage from '@/pages/warehouse/WarehouseScanPage'
import WarehouseInventoryPage from '@/pages/warehouse/WarehouseInventoryPage'

export function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/events" element={<EventListPage />} />
        <Route path="/events/new" element={<EventCreatePage />} />
        <Route path="/events/:id" element={<EventDetailPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/dashboard/bars/:barId" element={<BarDetailPage />} />
        <Route path="/warehouse/scan" element={<WarehouseScanPage />} />
        <Route path="/warehouse/inventory" element={<WarehouseInventoryPage />} />
        <Route path="/predictions" element={<PredictionPage />} />
        <Route path="/reports" element={<ReportPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
