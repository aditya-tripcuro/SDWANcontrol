import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from '../../src/pages/LoginPage'
import { AuthProvider } from '../../src/auth/AuthContext'

test('renders username and password input fields and sign in button', () => {
  render(<MemoryRouter><AuthProvider><LoginPage /></AuthProvider></MemoryRouter>)
  expect(screen.getByLabelText(/Username/i)).toBeInTheDocument()
  expect(screen.getByLabelText(/Password/i)).toBeInTheDocument()
  expect(screen.getByText(/Sign in/i)).toBeInTheDocument()
})

*** End Patch