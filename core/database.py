import os
import streamlit as st
from sqlalchemy import (
    create_engine, Column, Integer, String,
    Float, DateTime, Boolean, ForeignKey, Text
)
from sqlalchemy.orm import (
    declarative_base, relationship, sessionmaker
)
from datetime import datetime

Base = declarative_base()


class WaterSystem(Base):
    __tablename__ = "water_systems"
    id             = Column(Integer, primary_key=True)
    name           = Column(String, nullable=False)
    district       = Column(String)
    country        = Column(String, default="Uganda")
    currency       = Column(String, default="UGX")
    tariff_per_m3  = Column(Float, default=2500.0)
    tariff_psp     = Column(Float, default=2500.0)
    tariff_private = Column(Float, default=3000.0)
    mwater_form_id = Column(String)
    uses_mwater    = Column(Boolean, default=True)
    phone_prefix   = Column(String, default="+256")
    latitude       = Column(Float)
    longitude      = Column(Float)
    is_active      = Column(Boolean, default=True)
    created_at     = Column(DateTime,
                            default=datetime.utcnow)
    users       = relationship(
        "User", back_populates="system"
    )
    customers   = relationship(
        "Customer", back_populates="system"
    )
    readings    = relationship(
        "DailyReading", back_populates="system"
    )
    bills       = relationship(
        "Bill", back_populates="system"
    )
    nrw_records = relationship(
        "NRWRecord", back_populates="system"
    )
    payments    = relationship(
        "Payment", back_populates="system"
    )
    assets      = relationship(
        "Asset", back_populates="system"
    )


class User(Base):
    __tablename__ = "users"
    id           = Column(Integer, primary_key=True)
    system_id    = Column(
        Integer, ForeignKey("water_systems.id"),
        nullable=True
    )
    email        = Column(
        String, unique=True, nullable=False
    )
    name         = Column(String)
    role         = Column(String, default="viewer")
    password     = Column(String, nullable=False)
    is_active    = Column(Boolean, default=True)
    is_approved  = Column(Boolean, default=False)
    requested_at = Column(DateTime,
                          default=datetime.utcnow)
    created_at   = Column(DateTime,
                          default=datetime.utcnow)
    system       = relationship(
        "WaterSystem", back_populates="users"
    )


class Asset(Base):
    __tablename__ = "assets"
    id          = Column(Integer, primary_key=True)
    system_id   = Column(
        Integer, ForeignKey("water_systems.id"),
        nullable=False
    )
    name        = Column(String, nullable=False)
    asset_type  = Column(String)
    shape       = Column(String,
                         default="rectangular")
    length_m    = Column(Float)
    width_m     = Column(Float)
    diameter_m  = Column(Float)
    height_m    = Column(Float)
    capacity_m3 = Column(Float)
    latitude    = Column(Float)
    longitude   = Column(Float)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime,
                         default=datetime.utcnow)
    system      = relationship(
        "WaterSystem", back_populates="assets"
    )
    readings    = relationship(
        "MeterReading", back_populates="asset"
    )
    tank_levels = relationship(
        "TankLevel", back_populates="asset"
    )


class Customer(Base):
    __tablename__ = "customers"
    id                = Column(
        Integer, primary_key=True
    )
    system_id         = Column(
        Integer, ForeignKey("water_systems.id"),
        nullable=False
    )
    name              = Column(String, nullable=False)
    account_no        = Column(String, nullable=False)
    phone             = Column(String)
    address           = Column(String)
    meter_no          = Column(String)
    connection_type   = Column(String, default="PSP")
    opening_reading   = Column(Float, default=0.0)
    last_reading      = Column(Float, default=0.0)
    last_reading_date = Column(DateTime)
    latitude          = Column(Float)
    longitude         = Column(Float)
    is_active         = Column(Boolean, default=True)
    created_at        = Column(DateTime,
                               default=datetime.utcnow)
    system         = relationship(
        "WaterSystem", back_populates="customers"
    )
    bills          = relationship(
        "Bill", back_populates="customer"
    )
    meter_readings = relationship(
        "MeterReading", back_populates="customer"
    )
    payments       = relationship(
        "Payment", back_populates="customer"
    )


class MeterReading(Base):
    __tablename__ = "meter_readings"
    id            = Column(Integer, primary_key=True)
    system_id     = Column(
        Integer, ForeignKey("water_systems.id"),
        nullable=False
    )
    asset_id      = Column(
        Integer, ForeignKey("assets.id"),
        nullable=True
    )
    customer_id   = Column(
        Integer, ForeignKey("customers.id"),
        nullable=True
    )
    reading_type  = Column(String)
    reading_date  = Column(DateTime,
                           default=datetime.utcnow)
    start_reading = Column(Float)
    end_reading   = Column(Float)
    volume        = Column(Float)
    latitude      = Column(Float)
    longitude     = Column(Float)
    created_at    = Column(DateTime,
                           default=datetime.utcnow)
    asset    = relationship(
        "Asset", back_populates="readings"
    )
    customer = relationship(
        "Customer", back_populates="meter_readings"
    )


class TankLevel(Base):
    __tablename__ = "tank_levels"
    id           = Column(Integer, primary_key=True)
    system_id    = Column(
        Integer, ForeignKey("water_systems.id"),
        nullable=False
    )
    asset_id     = Column(
        Integer, ForeignKey("assets.id"),
        nullable=False
    )
    reading_date = Column(DateTime,
                          default=datetime.utcnow)
    level_m      = Column(Float, nullable=False)
    volume_m3    = Column(Float, nullable=False)
    pct_full     = Column(Float, nullable=False)
    latitude     = Column(Float)
    longitude    = Column(Float)
    created_at   = Column(DateTime,
                          default=datetime.utcnow)
    asset = relationship(
        "Asset", back_populates="tank_levels"
    )


class DailyReading(Base):
    __tablename__ = "daily_readings"
    id                 = Column(
        Integer, primary_key=True
    )
    system_id          = Column(
        Integer, ForeignKey("water_systems.id"),
        nullable=False
    )
    reading_date       = Column(
        DateTime, nullable=False
    )
    water_produced_m3  = Column(Float, default=0.0)
    water_sold_m3      = Column(Float, default=0.0)
    water_consumed_m3  = Column(Float, default=0.0)
    rainfall_mm        = Column(Float)
    mwater_response_id = Column(
        String, unique=True
    )
    synced_at          = Column(
        DateTime, default=datetime.utcnow
    )
    system = relationship(
        "WaterSystem", back_populates="readings"
    )


class Bill(Base):
    __tablename__ = "bills"
    id            = Column(Integer, primary_key=True)
    system_id     = Column(
        Integer, ForeignKey("water_systems.id"),
        nullable=False
    )
    customer_id   = Column(
        Integer, ForeignKey("customers.id"),
        nullable=False
    )
    bill_month    = Column(String, nullable=False)
    units_m3      = Column(Float)
    amount        = Column(Float)
    amount_paid   = Column(Float, default=0.0)
    is_paid       = Column(Boolean, default=False)
    sms_sent      = Column(Boolean, default=False)
    whatsapp_sent = Column(Boolean, default=False)
    created_at    = Column(DateTime,
                           default=datetime.utcnow)
    system   = relationship(
        "WaterSystem", back_populates="bills"
    )
    customer = relationship(
        "Customer", back_populates="bills"
    )
    payments = relationship(
        "Payment", back_populates="bill"
    )


class Payment(Base):
    __tablename__ = "payments"
    id             = Column(Integer, primary_key=True)
    system_id      = Column(
        Integer, ForeignKey("water_systems.id"),
        nullable=False
    )
    customer_id    = Column(
        Integer, ForeignKey("customers.id"),
        nullable=True
    )
    bill_id        = Column(
        Integer, ForeignKey("bills.id"),
        nullable=True
    )
    amount         = Column(Float)
    payment_method = Column(String, default="cash")
    reference      = Column(String)
    notes          = Column(Text)
    recorded_by    = Column(Integer)
    transaction_id = Column(String, nullable=True)
    network        = Column(String)
    status         = Column(String,
                            default="completed")
    paid_at        = Column(DateTime,
                            default=datetime.utcnow)
    created_at     = Column(DateTime,
                            default=datetime.utcnow)
    system   = relationship(
        "WaterSystem", back_populates="payments"
    )
    customer = relationship(
        "Customer", back_populates="payments"
    )
    bill     = relationship(
        "Bill", back_populates="payments"
    )


class NRWRecord(Base):
    __tablename__ = "nrw_records"
    id             = Column(Integer, primary_key=True)
    system_id      = Column(
        Integer, ForeignKey("water_systems.id"),
        nullable=False
    )
    month          = Column(String, nullable=False)
    water_produced = Column(Float)
    water_billed   = Column(Float)
    nrw_m3         = Column(Float)
    nrw_percent    = Column(Float)
    alert_sent     = Column(Boolean, default=False)
    created_at     = Column(DateTime,
                            default=datetime.utcnow)
    system = relationship(
        "WaterSystem", back_populates="nrw_records"
    )


@st.cache_resource
def get_engine():
    db_url = st.secrets.get("DATABASE_URL", "")
    if not db_url:
        db_url = os.environ.get(
            "DATABASE_URL",
            "sqlite:///maji360.db"
        )
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    return engine


def get_session():
    engine  = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()
