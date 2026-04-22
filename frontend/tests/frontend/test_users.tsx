import React from 'react'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import UsersPage from '../../src/pages/UsersPage'
import { AuthProvider } from '../../src/auth/AuthContext'

test('renders users page', () => {
  render(<MemoryRouter><AuthProvider><UsersPage /></AuthProvider></MemoryRouter>)
  expect(screen.getByText(/Users/i)).toBeInTheDocument()
})
