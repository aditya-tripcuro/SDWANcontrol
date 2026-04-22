import React from 'react'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ConfigPage from '../../src/pages/ConfigPage'
import { AuthProvider } from '../../src/auth/AuthContext'

test('renders config page', () => {
  render(<MemoryRouter><AuthProvider><ConfigPage /></AuthProvider></MemoryRouter>)
  expect(screen.getByText(/Config/i)).toBeInTheDocument()
})
