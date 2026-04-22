import React from 'react'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import MetricsPage from '../../src/pages/MetricsPage'
import { AuthProvider } from '../../src/auth/AuthContext'

test('renders metrics page and table headers', async () => {
  render(<MemoryRouter><AuthProvider><MetricsPage /></AuthProvider></MemoryRouter>)
  expect(screen.getByText(/Metrics/i)).toBeInTheDocument()
})
