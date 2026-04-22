import React from 'react'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import AlertsPage from '../../src/pages/AlertsPage'
import { AuthProvider } from '../../src/auth/AuthContext'

test('renders alerts page', () => {
  render(<MemoryRouter><AuthProvider><AlertsPage /></AuthProvider></MemoryRouter>)
  expect(screen.getByRole('heading', { name: /Alerts/i })).toBeInTheDocument()
})
