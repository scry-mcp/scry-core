DEFINE_DEVICE_TYPE(PIC8259, pic8259_device, "pic8259", "Intel 8259 PIC")
DEFINE_DEVICE_TYPE(V5X_ICU, v5x_icu_device, "v5x_icu", "NEC V5X ICU")
DEFINE_DEVICE_TYPE(MK98PIC, mk98pic_device, "mk98pic", "Elektronika MK-98 PIC")

uint8_t pic8259_device::read(offs_t offset)
{
	/* NPW 18-May-2003 - Changing 0xFF to 0x00 as per Ruslan */
	uint8_t data = 0x00;

	switch(offset)
	{
		case 0: /* PIC acknowledge IRQ */
			if ( m_ocw3 & 0x04 )
			{
				/* Polling mode */
				if (m_current_level != -1)
				{
					data = 0x80 | m_current_level;

					if (!machine().side_effects_disabled())
					{
						if (!m_level_trig_mode && (!m_master || !BIT(m_slave, m_current_level)))
							m_irr &= ~(1 << m_current_level);

						if (!m_auto_eoi)
							m_isr |= 1 << m_current_level;

						m_irq_timer->adjust(attotime::zero);
					}
				}

				if (!machine().side_effects_disabled())
					m_ocw3 &= 0xfb;
			}
			else
			{
				switch ( m_ocw3 & 0x01 )
				{
				case 0:
					data = m_irr;
					break;
				case 1:
					data = m_isr & ~m_imr;
					break;
				}
			}
			break;

		case 1: /* PIC mask register */
			data = m_imr;
			break;
	}
	return data;
}
