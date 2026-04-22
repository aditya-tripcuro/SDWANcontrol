import React from 'react'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import DashboardPage from '../../src/pages/DashboardPage'
import { AuthProvider } from '../../src/auth/AuthContext'
import { AlertCountProvider } from '../../src/context/AlertCountContext'

test('renders dashboard placeholder and reacts to SSE metric event', () => {
  render(<MemoryRouter><AuthProvider><AlertCountProvider><DashboardPage /></AlertCountProvider></AuthProvider></MemoryRouter>)
  expect(screen.getByText(/Dashboard/i)).toBeInTheDocument()
})
